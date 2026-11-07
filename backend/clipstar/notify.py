"""Notifications: shown in the app (bell) and, if SMTP is set up, emailed to people who want them.

Most notifications come from one place: a database hook that watches for the moments that need a person
(video ready or failed, a post that failed, an account that needs reconnecting, a batch made by a rule
waiting for approval, a business enquiry, a new weekly report). So no code path can forget to notify.
Each has a dedupe key, so a burst of failures becomes one notification, not fifty.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Account,
    AccountStatus,
    Batch,
    BatchStatus,
    Comment,
    CommentCategory,
    Notification,
    Post,
    PostStatus,
    Report,
    User,
    Video,
    VideoStatus,
)

log = logging.getLogger("clipstar.notify")
EMAIL_KIND = "notify.email"


def now() -> datetime:
    return datetime.now(timezone.utc)


def notify(s: Session, ws_id: uuid.UUID, kind: str, title: str, body: str = "", link: str | None = None, severity: str = "info", dedupe: str | None = None) -> None:
    """Record a notification. Uses the raw connection so it's safe inside a flush; duplicates are ignored."""
    stmt = insert(Notification).values(id=uuid.uuid4(), workspace_id=ws_id, kind=kind, title=title[:300], body=body, link=link, severity=severity, dedupe_key=dedupe[:200] if dedupe else None)
    s.connection().execute(stmt.on_conflict_do_nothing(index_elements=[Notification.dedupe_key]))


def _changed_to(obj, attr: str, value) -> bool:
    h = inspect(obj).attrs[attr].history
    return bool(h.added) and h.added[0] == value and (not h.deleted or h.deleted[0] != value)


def _day() -> str:
    return now().strftime("%Y-%m-%d")


@event.listens_for(Session, "before_flush")
def _watch(s: Session, _ctx, _instances) -> None:
    try:
        with s.no_autoflush:
            _scan(s)
    except Exception:  # notifications must never break the work that triggered them
        log.exception("notification hook failed")


def _val(x) -> str:
    return getattr(x, "value", x)


def _scan(s: Session) -> None:
    for obj in list(s.dirty) + list(s.new):
        new = obj in s.new
        if new and hasattr(obj, "id") and getattr(obj, "id", None) is None and isinstance(obj, (Batch, Comment, Report, Post)):
            obj.id = uuid.uuid4()  # events need the id now; it's normally set at insert
        for fn in ((_scan_new, _events_new) if new else (_scan_dirty, _events_dirty)):
            try:
                fn(s, obj)
            except Exception:  # one odd object must not hide the others
                log.exception("notification/event check failed for %r", obj)


def _ws_of_post(s: Session, p: Post):
    b = s.get(Batch, p.batch_id)
    return b.workspace_id if b else None


def _events_dirty(s: Session, obj) -> None:
    from .events import emit
    from .models import Clip, ClipStatus

    if isinstance(obj, Video):
        if _changed_to(obj, "status", VideoStatus.ready):
            n = s.scalar(select(func.count(Clip.id)).where(Clip.video_id == obj.id)) or 0
            emit(s, obj.workspace_id, "video.ready", {"video_id": obj.id, "title": obj.title, "clips": n, "link": f"/videos/{obj.id}"})
        elif _changed_to(obj, "status", VideoStatus.failed):
            emit(s, obj.workspace_id, "video.failed", {"video_id": obj.id, "title": obj.title, "error": obj.error, "stage": _val(obj.stage)})
    elif isinstance(obj, Clip):
        for st in (ClipStatus.approved, ClipStatus.rejected):
            if _changed_to(obj, "status", st):
                v = s.get(Video, obj.video_id)
                if v:
                    emit(s, v.workspace_id, f"clip.{st.value}", {"clip_id": obj.id, "video_id": obj.video_id, "title": obj.title, "score": obj.score, "link": f"/clips/{obj.id}"})
    elif isinstance(obj, Batch) and _changed_to(obj, "status", BatchStatus.running) and inspect(obj).attrs["status"].history.deleted == [BatchStatus.awaiting]:
        emit(s, obj.workspace_id, "batch.approved", {"batch_id": obj.id, "name": obj.name})
    elif isinstance(obj, Account) and _changed_to(obj, "status", AccountStatus.reconnect):
        emit(s, obj.workspace_id, "account.needs_reconnect", {"account_id": obj.id, "platform": _val(obj.platform), "handle": obj.handle, "reason": obj.last_error})
    elif isinstance(obj, Post):
        for st, kind in ((PostStatus.published, "post.published"), (PostStatus.failed, "post.failed")):
            if _changed_to(obj, "status", st):
                ws = _ws_of_post(s, obj)
                a = s.get(Account, obj.account_id)
                if ws:
                    emit(s, ws, kind, {
                        "post_id": obj.id, "batch_id": obj.batch_id, "clip_id": obj.clip_id, "variant": obj.variant,
                        "account_id": obj.account_id, "platform": _val(a.platform) if a else None, "handle": a.handle if a else None,
                        "remote_id": obj.remote_id, "url": obj.remote_url, "error": obj.last_error if st == PostStatus.failed else None,
                    })


def _events_new(s: Session, obj) -> None:
    from .events import emit

    if isinstance(obj, Batch) and obj.status in (BatchStatus.awaiting, None):
        emit(s, obj.workspace_id, "batch.awaiting_approval", {"batch_id": obj.id, "name": obj.name, "origin": obj.origin, "link": "/publishing"})
    elif isinstance(obj, Comment):
        a = s.get(Account, obj.account_id)
        if a is not None:
            emit(s, a.workspace_id, "comment.received", {"comment_id": obj.id, "account_id": a.id, "platform": _val(a.platform), "post_id": obj.post_id, "author": obj.author, "message": (obj.message or "")[:1000], "category": _val(obj.category)})
    elif isinstance(obj, Report):
        emit(s, obj.workspace_id, "report.ready", {"report_id": obj.id, "summary": obj.summary, "link": "/analytics"})


def _scan_dirty(s: Session, obj) -> None:
    if isinstance(obj, Video):
        if _changed_to(obj, "status", VideoStatus.ready):
            notify(s, obj.workspace_id, "video_ready", f"“{obj.title}” is ready", "New clips are waiting for review.", f"/videos/{obj.id}", dedupe=f"video_ready:{obj.id}:{now():%Y%m%d%H%M}")
        elif _changed_to(obj, "status", VideoStatus.failed):
            notify(s, obj.workspace_id, "video_failed", f"“{obj.title}” stopped", obj.error or "Processing failed. Open the video to retry.", f"/videos/{obj.id}", "error", dedupe=f"video_failed:{obj.id}:{now():%Y%m%d%H%M}")
    elif isinstance(obj, Account) and _changed_to(obj, "status", AccountStatus.reconnect):
        notify(s, obj.workspace_id, "reconnect", f"Reconnect {obj.handle} ({_val(obj.platform)})", obj.last_error or "The login expired. Posts for this account wait until it's reconnected.", f"/accounts/{obj.id}", "warn", dedupe=f"reconnect:{obj.id}:{_day()}")
    elif isinstance(obj, Post) and _changed_to(obj, "status", PostStatus.failed):
        b = s.get(Batch, obj.batch_id)
        if b is not None:
            notify(s, b.workspace_id, "post_problem", f"Posts need attention in “{b.name}”", obj.last_error or "A post failed.", f"/posts?batch_id={b.id}", "error", dedupe=f"post_problem:{b.id}:{_day()}")


def _scan_new(s: Session, obj) -> None:
    if isinstance(obj, Batch) and obj.origin and obj.status in (BatchStatus.awaiting, None):
        notify(s, obj.workspace_id, "needs_approval", f"Batch “{obj.name}” is waiting for approval", "An automation rule scheduled new posts. Nothing goes out until you approve.", "/publishing", dedupe=f"needs_approval:{obj.origin}")
    elif isinstance(obj, Comment) and obj.category == CommentCategory.lead:
        a = s.get(Account, obj.account_id)
        if a is not None:
            notify(s, a.workspace_id, "lead", f"Business enquiry from {obj.author or 'a viewer'}", (obj.message or "")[:300], "/engage", dedupe=f"lead:{obj.account_id}:{obj.remote_id}")
    elif isinstance(obj, Report):
        notify(s, obj.workspace_id, "report", "Your weekly report is ready", (obj.summary or "")[:500], "/analytics", dedupe=f"report:{obj.workspace_id}:{_day()}")


# ---------- email ----------


def recipients(s: Session, ws_id: uuid.UUID, kind: str) -> list[str]:
    from .models import Membership

    out = []
    rows = s.execute(
        select(User.email, Membership.prefs).join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == ws_id, Membership.disabled.is_(False), User.disabled.is_(False), User.password_hash.is_not(None))
    )
    for email, prefs in rows:
        prefs = prefs or {}
        kinds = prefs.get("kinds")
        if prefs.get("email", True) and (kinds is None or kind in kinds):
            out.append(email)
    return out


def dispatch_email() -> int:
    """Queue one email job per notification not yet emailed (last 2 days only, so a new SMTP setup doesn't send old news)."""
    from . import mailer
    from .db import session_scope
    from .jobs import queue

    if not mailer.configured():
        return 0
    n = 0
    with session_scope() as s:
        for nt in s.scalars(select(Notification).where(Notification.emailed_at.is_(None), Notification.created_at > now() - timedelta(days=2)).limit(50)):
            queue.enqueue(s, EMAIL_KIND, {"id": str(nt.id)}, dedupe_key=f"email:{nt.id}", priority=60, max_attempts=4)
            n += 1
    return n


def run_email(ctx) -> dict:
    from . import mailer
    from .db import session_scope

    nid = uuid.UUID(ctx.payload["id"])
    with session_scope() as s:
        nt = s.get(Notification, nid)
        if nt is None or nt.emailed_at is not None:
            return {"skipped": True}
        to = recipients(s, nt.workspace_id, nt.kind)
        subject = f"[clip_star] {nt.title}"
        path = nt.link or "/"
        path += ("&" if "?" in path else "?") + f"ws={nt.workspace_id}"  # opens in the right workspace
        link = f"{get_settings().web_url.rstrip('/')}{path}"
        body = f"{nt.body}\n\nOpen: {link}\n\nChange which emails you get in clip_star → Settings → Notifications."
    if to:
        mailer.send(to, subject, body)
    with session_scope() as s:
        nt = s.get(Notification, nid, with_for_update=True)
        if nt is not None:
            nt.emailed_at = now()
    return {"sent_to": len(to)}


def _email_failed(s: Session, job) -> None:
    # gave up (e.g. SMTP login wrong): don't retry this one forever; it stays visible in the app
    nt = s.get(Notification, uuid.UUID(job.payload["id"]), with_for_update=True)
    if nt is not None and nt.emailed_at is None:
        nt.emailed_at = now()


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(EMAIL_KIND, Handler(run=run_email, on_failure=_email_failed))
