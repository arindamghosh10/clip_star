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

from sqlalchemy import event, inspect, select
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
        try:
            if obj in s.new:
                _scan_new(s, obj)
            else:
                _scan_dirty(s, obj)
        except Exception:  # one odd object must not hide the others
            log.exception("notification check failed for %r", obj)


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
    out = []
    for u in s.scalars(select(User).where(User.workspace_id == ws_id, User.disabled.is_(False), User.password_hash.is_not(None))):
        prefs = u.prefs or {}
        kinds = prefs.get("kinds")
        if prefs.get("email", True) and (kinds is None or kind in kinds):
            out.append(u.email)
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
        link = f"{get_settings().web_url.rstrip('/')}{nt.link}" if nt.link else get_settings().web_url
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
