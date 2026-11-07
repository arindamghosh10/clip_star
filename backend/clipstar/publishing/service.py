"""Publishing: build batches, dispatch due posts, publish, verify. The "never post twice" logic lives here.

Post states:
  held -> scheduled (batch approved) -> publishing -> published
                                                   -> failed      (permanent problem, or retries used up)
                                                   -> unknown     (the platform may have posted; we verify)
  unknown -> published (found on the platform) | failed (not found: the user decides whether to retry)

A post is only sent to a platform when it is `scheduled`, its batch is `running`, and its account is
connected. Uncertain outcomes are never retried automatically.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..errors import ClipstarError, PermanentError, RetryableError
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..models import (
    Account,
    AccountStatus,
    Batch,
    BatchStatus,
    Clip,
    ClipStatus,
    Job,
    JobStatus,
    PlatformApp,
    Post,
    PostStatus,
    Rule,
    Video,
    Workspace,
)
from ..pipeline.package import compose
from ..platforms.base import Ambiguous, App, AuthExpired, PublishRequest, Tokens
from ..platforms.registry import provider_for
from ..secrets import decrypt, decrypt_json, encrypt  # noqa: F401  (encrypt re-exported for tests)
from ..storage import get_storage
from .scheduler import AccountInfo, ClipInfo, plan

log = logging.getLogger("clipstar.publishing")

PUBLISH_KIND = "post.publish"
VERIFY_KIND = "post.verify"
RULES_KIND = "rules.apply"
MAX_PUBLISH_TRIES = 5
VERIFY_DELAYS = [60, 300, 900]  # seconds before each verification check
STUCK_AFTER = timedelta(minutes=30)
ACTIVE_POST = (PostStatus.held, PostStatus.scheduled, PostStatus.publishing, PostStatus.unknown)


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- batches ----------


def account_info(a: Account) -> AccountInfo:
    return AccountInfo(id=str(a.id), platform=a.platform.value, handle=a.handle, timezone=a.timezone, start=a.posting_start, end=a.posting_end, daily_cap=a.daily_cap, status=a.status.value)


def clip_info(c: Clip) -> ClipInfo:
    renders = (c.meta or {}).get("renders") or {}
    st = get_storage()
    variants = [v["id"] for v in (c.variants or []) if v["id"] in renders and st.exists(renders[v["id"]]["path"])]
    return ClipInfo(id=str(c.id), title=c.title, variants=variants, preflight=(c.meta or {}).get("preflight") or {})


def existing_times(s: Session, account_ids: list[uuid.UUID]) -> dict[str, list[datetime]]:
    rows = s.execute(
        select(Post.account_id, Post.scheduled_at, Post.published_at).where(
            Post.account_id.in_(account_ids), Post.status.in_([PostStatus.scheduled, PostStatus.publishing, PostStatus.published, PostStatus.held])
        )
    )
    out: dict[str, list[datetime]] = {}
    for aid, sched, pub in rows:
        out.setdefault(str(aid), []).append(pub or sched)
    return out


def disclosure_warnings(s: Session, clips: list[Clip], accounts: list[Account]) -> list[str]:
    """Things the creator should know before posting: AI labels a platform can't take, and music without a licence note."""
    from ..models import MusicTrack
    from ..platforms.base import AI_LABEL_PLATFORMS

    out: list[str] = []
    platforms = sorted({a.platform.value for a in accounts})
    for c in clips:
        if ai_content(c):
            manual = [p for p in platforms if p not in AI_LABEL_PLATFORMS]
            if manual:
                out.append(f"“{c.title}” is marked AI-altered. {', '.join(manual)} can't take that label through their API; add it in the app after posting.")
        for v in c.variants or []:
            tid = (v.get("music") or {}).get("track_id")
            if tid:
                t = s.get(MusicTrack, uuid.UUID(tid))
                if t is not None and not t.license_note:
                    out.append(f"“{c.title}” uses the track “{t.title}” with no licence note. Platforms may mute or block music they recognise.")
    return list(dict.fromkeys(out))


def build_plan(s: Session, ws: Workspace, clips: list[Clip], accounts: list[Account], start_at: datetime, spacing_min: int | None, variations: str):
    p = _plan(s, ws, clips, accounts, start_at, spacing_min, variations)
    p.warnings = list(p.warnings) + disclosure_warnings(s, clips, accounts)
    return p


def _plan(s: Session, ws: Workspace, clips: list[Clip], accounts: list[Account], start_at: datetime, spacing_min: int | None, variations: str):
    st = ws.settings or {}
    return plan(
        [clip_info(c) for c in clips],
        [account_info(a) for a in accounts],
        start_at,
        existing_times(s, [a.id for a in accounts]),
        spacing_min=spacing_min if spacing_min is not None else int(st.get("spacing_minutes", 45)),
        variations=variations,
        quiet_hours=bool(st.get("quiet_hours", True)),
        duplicate_warning=int(st.get("duplicate_warning_accounts", 5)),
    )


def create_batch(s: Session, ws: Workspace, name: str, clips: list[Clip], accounts: list[Account], start_at: datetime, spacing_min: int | None, variations: str, origin: str = "manual"):
    p = build_plan(s, ws, clips, accounts, start_at, spacing_min, variations)
    if not p.slots:
        reasons = "; ".join(sorted({x["reason"] for x in p.skipped})[:3]) or "nothing to post"
        raise PermanentError("empty batch", user_message=f"No posts could be scheduled: {reasons}")
    b = Batch(workspace_id=ws.id, name=name[:300], variations=variations, origin=origin, warnings=p.warnings + [x["reason"] for x in p.skipped][:50])
    s.add(b)
    s.flush()
    by_clip = {str(c.id): c for c in clips}
    by_acc = {str(a.id): a for a in accounts}
    for sl in p.slots:
        c, a = by_clip[sl.clip_id], by_acc[sl.account_id]
        cp = (c.copy or {}).get(a.platform.value)
        caption = compose(cp, a.platform.value) if isinstance(cp, dict) else (cp if isinstance(cp, str) else c.title)
        s.add(Post(batch_id=b.id, account_id=a.id, clip_id=c.id, variant=sl.variant, caption=caption, scheduled_at=sl.at, status=PostStatus.held))
    s.flush()
    return b, p


def finish_batch_if_done(s: Session, batch_id: uuid.UUID) -> None:
    b = s.get(Batch, batch_id, with_for_update=True)
    if b is None or b.status not in (BatchStatus.running, BatchStatus.disabled):
        return
    open_posts = s.scalar(select(func.count()).select_from(Post).where(Post.batch_id == b.id, Post.status.in_(ACTIVE_POST)))
    if not open_posts:
        b.status = BatchStatus.finished


# ---------- tokens ----------


def get_app(s: Session, workspace_id: uuid.UUID, platform: str) -> App | None:
    row = s.get(PlatformApp, (workspace_id, platform))
    if row is None:
        return None
    return App(row.client_id, decrypt(row.secret_enc))


def save_tokens(a: Account, t: Tokens) -> None:
    a.token_enc = encrypt(t.to_dict())
    a.token_expires_at = datetime.fromtimestamp(t.expires_at, timezone.utc) if t.expires_at else None


def fresh_tokens(account_id: uuid.UUID) -> tuple[App | None, Tokens | None]:
    """Load (and refresh if needed) an account's tokens. Marks the account for reconnect when that's the only fix."""
    with session_scope() as s:
        a = s.get(Account, account_id, with_for_update=True)
        if a.connection == "simulated":
            return None, None
        app = get_app(s, a.workspace_id, a.platform.value)
        if app is None:
            raise PermanentError("no app", user_message=f"Add your {a.platform.value} app keys in Settings → Platform apps.")
        if not a.token_enc:
            a.status = AccountStatus.reconnect
            raise AuthExpired("no token", user_message="This account isn't connected. Reconnect it.")
        tokens = Tokens.from_dict(decrypt_json(a.token_enc))
        if tokens.expiring(600):
            prov = provider_for(a.platform.value, a.connection)
            new = prov.refresh(app, tokens)
            if new is None:
                if tokens.expiring(0):
                    a.status = AccountStatus.reconnect
                    raise AuthExpired("expired", user_message=f"The {a.platform.value} login expired. Reconnect the account.")
            else:
                save_tokens(a, new)
                tokens = new
        return app, tokens


# ---------- dispatch (runs in every worker loop) ----------


def dispatch(limit: int = 50) -> int:
    """Queue publish jobs for due posts; recover posts stuck in `publishing`. Safe to run from many workers."""
    n = 0
    with session_scope() as s:
        due = s.scalars(
            select(Post)
            .join(Batch, Batch.id == Post.batch_id)
            .where(Post.status == PostStatus.scheduled, Post.scheduled_at <= now(), Batch.status == BatchStatus.running)
            .order_by(Post.scheduled_at)
            .limit(limit)
            .with_for_update(of=Post, skip_locked=True)
        ).all()
        for p in due:
            queue.enqueue(s, PUBLISH_KIND, {"post_id": str(p.id)}, dedupe_key=f"post:{p.id}:publish", priority=20, max_attempts=3)
            n += 1
        # a worker died mid-publish: we don't know if it posted -> verify, never re-send blindly
        stuck = s.scalars(
            select(Post).where(Post.status == PostStatus.publishing, Post.started_at < now() - STUCK_AFTER).with_for_update(skip_locked=True).limit(limit)
        ).all()
        for p in stuck:
            active = s.scalar(select(func.count()).select_from(Job).where(Job.dedupe_key == f"post:{p.id}:publish", Job.status.in_([JobStatus.queued, JobStatus.running])))
            if not active:
                p.status = PostStatus.unknown
                p.last_error = "Publishing was interrupted; checking whether the post went out."
                _queue_verify(s, p)
    return n


def _queue_verify(s: Session, p: Post) -> None:
    delay = VERIFY_DELAYS[min(p.verify_attempts, len(VERIFY_DELAYS) - 1)]
    # one key per check: the running check must be able to queue the next one
    queue.enqueue(s, VERIFY_KIND, {"post_id": str(p.id)}, dedupe_key=f"post:{p.id}:verify:{p.verify_attempts}", run_after=now() + timedelta(seconds=delay), priority=20, max_attempts=3)


# ---------- publish ----------


def _local_window_ok(a: Account, at: datetime, quiet: bool) -> datetime | None:
    """None if `at` is fine; else the next allowed time."""
    if not quiet:
        return None
    from .scheduler import next_slot

    nxt = next_slot(account_info(a), at, [], 0, True)
    return None if nxt is None or nxt <= at + timedelta(seconds=1) else nxt


def ai_content(c: Clip) -> bool:
    """Whether to disclose this clip as AI-altered: set by hand on the clip, or by an AI step (e.g. dubbing)."""
    return bool((c.meta or {}).get("ai_content"))


def _request(s: Session, p: Post, a: Account, c: Clip) -> PublishRequest:
    st = get_storage()
    r = ((c.meta or {}).get("renders") or {}).get(p.variant)
    if not r or not st.exists(r["path"]):
        raise PermanentError("render missing", user_message=f"The rendered video for version {p.variant} is missing. Re-render the clip, then retry.")
    cp = (c.copy or {}).get(a.platform.value)
    title = cp.get("title", "") if isinstance(cp, dict) else ""
    tags = cp.get("hashtags", []) if isinstance(cp, dict) else []
    opts = dict(a.options or {})
    pub = public_media_url(r["path"])
    if pub:
        opts["_public_video_url"] = pub
    from ..pipeline.covers import cover_rel

    crel = cover_rel(c, p.variant)
    cover = st.abs(crel) if crel and st.exists(crel) else None
    return PublishRequest(video=st.abs(r["path"]), cover=cover, title=title or c.title, caption=p.caption, hashtags=tags, duration_s=c.end_s - c.start_s, post_id=str(p.id), account_options=opts, ai_generated=ai_content(c))


def run_publish(ctx: JobContext) -> dict:
    pid = uuid.UUID(ctx.payload["post_id"])
    # ---- 1. checks, and record the attempt before calling the platform ----
    with session_scope() as s:
        p = s.get(Post, pid, with_for_update=True)
        if p is None or p.status != PostStatus.scheduled:
            return {"skipped": "not scheduled"}
        b = s.get(Batch, p.batch_id)
        if b.status != BatchStatus.running:
            return {"skipped": f"batch {b.status.value}"}  # disabled after it was queued
        a = s.get(Account, p.account_id)
        c = s.get(Clip, p.clip_id)
        ws = s.get(Workspace, a.workspace_id)
        if a.status in (AccountStatus.paused, AccountStatus.reconnect, AccountStatus.disconnected):
            p.scheduled_at = now() + timedelta(hours=1)
            p.last_error = f"Waiting: the account is {a.status.value}."
            return {"rescheduled": "account not available"}
        if c is None or c.status == ClipStatus.rejected:
            p.status = PostStatus.cancelled
            p.last_error = "The clip was rejected."
            finish_batch_if_done(s, p.batch_id)
            return {"cancelled": "clip rejected"}
        later = _local_window_ok(a, now(), bool((ws.settings or {}).get("quiet_hours", True)))
        if later:
            p.scheduled_at = later
            p.last_error = "Moved to the account's next posting hours."
            return {"rescheduled": later.isoformat()}
        tz = ZoneInfo(a.timezone)
        day_start = now().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today = s.scalar(
            select(func.count()).select_from(Post).where(Post.account_id == a.id, Post.status == PostStatus.published, Post.published_at >= day_start.astimezone(timezone.utc))
        )
        if today >= a.daily_cap:
            p.scheduled_at = (day_start + timedelta(days=1)).astimezone(timezone.utc)
            p.last_error = f"Daily limit of {a.daily_cap} reached; moved to tomorrow."
            return {"rescheduled": "daily cap"}
        pf = ((c.meta or {}).get("preflight") or {}).get(a.platform.value)
        if pf is not None and not pf.get("ok", True):
            p.status = PostStatus.failed
            p.last_error = "Post text doesn't fit this platform: " + "; ".join(pf.get("problems", []))
            finish_batch_if_done(s, p.batch_id)
            return {"failed": "preflight"}
        try:
            req = _request(s, p, a, c)
        except PermanentError as e:
            p.status = PostStatus.failed
            p.last_error = e.user_message
            finish_batch_if_done(s, p.batch_id)
            return {"failed": "media"}
        account_id, platform, connection, remote_id = a.id, a.platform.value, a.connection, a.remote_id
        p.status = PostStatus.publishing
        p.started_at = now()
        p.attempts += 1
        attempt = p.attempts
    since = time.time() - 60

    # ---- 2. call the platform ----
    result = error = None
    try:
        app, tokens = fresh_tokens(account_id)
        result = provider_for(platform, connection).publish(app, tokens, remote_id or "", req)
    except AuthExpired as e:
        error = e
    except (RetryableError, PermanentError, Ambiguous) as e:
        error = e
    except Exception as e:  # an unexpected bug after the platform may have accepted the post: treat as uncertain
        log.exception("unexpected publish error for post %s", pid)
        error = Ambiguous(str(e), user_message="Something unexpected happened while publishing; checking whether the post went out.")

    # ---- 3. record the outcome ----
    with session_scope() as s:
        p = s.get(Post, pid, with_for_update=True)
        a = s.get(Account, account_id, with_for_update=True)
        if result is not None:
            p.status = PostStatus.published
            p.remote_id = result.remote_id
            p.remote_url = result.url
            p.published_at = now()
            p.last_error = result.note
            finish_batch_if_done(s, p.batch_id)
            return {"published": result.remote_id}
        assert error is not None
        msg = error.user_message if isinstance(error, ClipstarError) else str(error)
        if isinstance(error, AuthExpired):
            p.status = PostStatus.failed
            p.last_error = msg
            a.status = AccountStatus.reconnect
            a.last_error = msg
        elif isinstance(error, Ambiguous):
            p.status = PostStatus.unknown
            p.last_error = msg
            p.metrics = {**(p.metrics or {}), "_since": since}
            _queue_verify(s, p)
        elif isinstance(error, RetryableError) and attempt < MAX_PUBLISH_TRIES:
            p.status = PostStatus.scheduled
            p.scheduled_at = now() + timedelta(minutes=2 * 3 ** (attempt - 1))  # 2, 6, 18, 54 min
            p.last_error = msg
        else:
            p.status = PostStatus.failed
            p.last_error = msg
        finish_batch_if_done(s, p.batch_id)
        return {"outcome": p.status.value, "error": msg}


def run_verify(ctx: JobContext) -> dict:
    pid = uuid.UUID(ctx.payload["post_id"])
    with session_scope() as s:
        p = s.get(Post, pid)
        if p is None or p.status != PostStatus.unknown:
            return {"skipped": "not unknown"}
        a = s.get(Account, p.account_id)
        c = s.get(Clip, p.clip_id)
        try:
            req = _request(s, p, a, c)
        except PermanentError:
            req = PublishRequest(video=get_storage().root, cover=None, title=c.title if c else "", caption=p.caption, hashtags=[], duration_s=0, post_id=str(p.id), account_options=dict(a.options or {}))
        account_id, platform, connection, remote_id = a.id, a.platform.value, a.connection, a.remote_id
        since = float((p.metrics or {}).get("_since", time.time() - 3600))
        handle = a.handle
    found = None
    try:
        app, tokens = fresh_tokens(account_id)
        found = provider_for(platform, connection).find(app, tokens, remote_id or "", req, since)
    except (RetryableError, Ambiguous):
        pass  # try again at the next check
    except (PermanentError, AuthExpired):
        found = None
    with session_scope() as s:
        p = s.get(Post, pid, with_for_update=True)
        if p.status != PostStatus.unknown:
            return {"skipped": "changed"}
        if found:
            p.status = PostStatus.published
            p.remote_id = found.remote_id
            p.remote_url = found.url
            p.published_at = now()
            p.last_error = "Confirmed on the platform after an uncertain response."
            finish_batch_if_done(s, p.batch_id)
            return {"verified": found.remote_id}
        p.verify_attempts += 1
        if p.verify_attempts < len(VERIFY_DELAYS):
            _queue_verify(s, p)
            return {"verify": "will check again"}
        p.status = PostStatus.failed
        p.last_error = f"Couldn't confirm whether this was posted. Check {handle} on {platform}; if it's not there, retry it."
        finish_batch_if_done(s, p.batch_id)
        return {"verify": "gave up"}


# ---------- automation rules ----------


def run_rules(ctx: JobContext) -> dict:
    vid = uuid.UUID(ctx.payload["video_id"])
    made = []
    with session_scope() as s:
        v = s.get(Video, vid)
        if v is None:
            return {}
        ws = s.get(Workspace, v.workspace_id)
        rules = list(s.scalars(select(Rule).where(Rule.workspace_id == ws.id, Rule.enabled.is_(True))))
        for r in rules:
            cfg = r.config or {}
            origin = f"rule:{r.id}:{v.id}"
            if s.scalar(select(Batch.id).where(Batch.workspace_id == ws.id, Batch.origin == origin)):
                continue
            min_score = int(cfg.get("min_score", 0))
            clips = [c for c in s.scalars(select(Clip).where(Clip.video_id == v.id, Clip.status != ClipStatus.rejected).order_by(Clip.score.desc())) if c.score >= min_score]
            q = select(Account).where(Account.workspace_id == ws.id)
            if cfg.get("groups"):
                q = q.where(Account.group_name.in_(cfg["groups"]))
            if cfg.get("platforms"):
                q = q.where(Account.platform.in_(cfg["platforms"]))
            accounts = list(s.scalars(q))
            if not clips or not accounts:
                continue
            start = now() + timedelta(minutes=int(cfg.get("start_delay_minutes", 60)))
            try:
                with s.begin_nested():
                    b, _ = create_batch(s, ws, f"{r.name} · {v.title}", clips, accounts, start, cfg.get("spacing_minutes"), cfg.get("variations", "off"), origin=origin)
                made.append(str(b.id))
            except PermanentError as e:
                log.info("rule %s made no batch: %s", r.id, e.user_message)
    return {"batches": made}


def queue_rules(s: Session, video_id: uuid.UUID) -> None:
    queue.enqueue(s, RULES_KIND, {"video_id": str(video_id)}, dedupe_key=f"rules:{video_id}", priority=60)


# ---------- public media links (for platforms that fetch the video by URL, e.g. Threads) ----------


def public_media_url(rel_path: str, ttl_s: int = 6 * 3600) -> str | None:
    base = get_settings().public_media_url
    if not base:
        return None
    token = encrypt({"p": rel_path, "exp": time.time() + ttl_s})
    return f"{base.rstrip('/')}/api/public/media/{token}"


def register_handlers() -> None:
    register(PUBLISH_KIND, Handler(run=run_publish))
    register(VERIFY_KIND, Handler(run=run_verify))
    register(RULES_KIND, Handler(run=run_rules))
