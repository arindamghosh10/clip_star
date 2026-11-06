"""Engage: sync comments on our own posts, sort them, draft replies, send replies, hide spam.

Replies follow the same safety rules as posts:
- a reply is sent only when it is `queued` (by the creator, or by an auto-reply category they turned on)
- the attempt is recorded before calling the platform
- an uncertain result becomes `unknown` and is never re-sent automatically
- each account has an hourly reply limit; over it, replies wait
Only comments on the creator's own posts are touched. Nothing is posted anywhere else.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..engines.registry import chosen_engine_id, get_engine
from ..errors import ClipstarError, PermanentError, RetryableError
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..models import Account, AccountStatus, Clip, Comment, CommentCategory, Post, PostStatus, ReplyStatus, Stage, Workspace
from ..platforms.base import Ambiguous, AuthExpired
from ..platforms.registry import provider_for
from ..publishing.service import fresh_tokens
from .engines import CommentIn
from .rules import EngageSettings

log = logging.getLogger("clipstar.engage")

SYNC_KIND = "comments.sync"
REPLY_KIND = "comment.reply"
HIDE_KIND = "comment.hide"
RECENT_DAYS = 14
MAX_POSTS_PER_SYNC = 25
MAX_REPLY_TRIES = 4


def now() -> datetime:
    return datetime.now(timezone.utc)


def supports_comments(a: Account) -> bool:
    return provider_for(a.platform.value, a.connection).comments_supported


# ---------- sync ----------


def enqueue_sync(s: Session, account_id: uuid.UUID) -> None:
    queue.enqueue(s, SYNC_KIND, {"account_id": str(account_id)}, dedupe_key=f"comments:{account_id}", priority=70)


def dispatch_sync(force_workspace: uuid.UUID | None = None) -> int:
    """Queue comment syncs for accounts that are due (or all, for a manual 'sync now')."""
    n = 0
    with session_scope() as s:
        recent = now() - timedelta(days=RECENT_DAYS)
        q = (
            select(Account)
            .where(Account.status == AccountStatus.connected)
            .where(select(Post.id).where(Post.account_id == Account.id, Post.status == PostStatus.published, Post.published_at >= recent).exists())
        )
        if force_workspace:
            q = q.where(Account.workspace_id == force_workspace)
        for a in s.scalars(q):
            if not supports_comments(a):
                continue
            if not force_workspace:
                ws = s.get(Workspace, a.workspace_id)
                every = EngageSettings.from_workspace(ws.settings if ws else {}).sync_minutes
                if a.comments_synced_at and a.comments_synced_at > now() - timedelta(minutes=every):
                    continue
            enqueue_sync(s, a.id)
            n += 1
    return n


def _clip_context(c: Clip | None) -> tuple[str, str]:
    if c is None:
        return "", ""
    words = " ".join(w["word"] for w in (c.meta or {}).get("words", []))
    return c.title, words


def run_sync(ctx: JobContext) -> dict:
    aid = uuid.UUID(ctx.payload["account_id"])
    with session_scope() as s:
        a = s.get(Account, aid)
        if a is None or a.status != AccountStatus.connected or not supports_comments(a):
            return {"skipped": True}
        ws = s.get(Workspace, a.workspace_id)
        st = EngageSettings.from_workspace(ws.settings if ws else {})
        engine = get_engine(Stage.engage, chosen_engine_id(s, a.workspace_id, Stage.engage) or "rules") or get_engine(Stage.engage, "rules")
        posts = list(
            s.scalars(
                select(Post)
                .where(Post.account_id == aid, Post.status == PostStatus.published, Post.remote_id.is_not(None), Post.published_at >= now() - timedelta(days=RECENT_DAYS))
                .order_by(Post.published_at.desc())
                .limit(MAX_POSTS_PER_SYNC)
            )
        )
        post_info = [(p.id, p.remote_id, p.clip_id) for p in posts]
        known = set(s.scalars(select(Comment.remote_id).where(Comment.account_id == aid)))
        platform, connection, remote_id = a.platform.value, a.connection, a.remote_id or ""
        prov = provider_for(platform, connection)
        clips = {c.id: c for c in s.scalars(select(Clip).where(Clip.id.in_([p[2] for p in post_info])))} if post_info else {}
        ctx_by_post = {pid: _clip_context(clips.get(cid)) for pid, _, cid in post_info}

    try:
        app, tokens = fresh_tokens(aid)
    except AuthExpired as e:
        _mark_reconnect(aid, e.user_message)
        return {"error": "reconnect"}

    found: list[tuple[uuid.UUID, object]] = []
    problems = 0
    for i, (pid, prid, _) in enumerate(post_info):
        ctx.progress(80 * i / max(1, len(post_info)))
        try:
            for rc in prov.list_comments(app, tokens, remote_id, prid):
                if not rc.is_own and rc.remote_id not in known and rc.text.strip():
                    found.append((pid, rc))
                    known.add(rc.remote_id)
        except AuthExpired as e:
            _mark_reconnect(aid, e.user_message)
            return {"error": "reconnect"}
        except RetryableError:
            raise  # whole sync retries later
        except (PermanentError, Ambiguous) as e:
            problems += 1  # e.g. the post was deleted on the platform
            log.info("comment sync skipped a post for %s: %s", aid, e)

    items = [
        CommentIn(id=rc.remote_id, author=rc.author, text=rc.text, platform=platform, clip_title=ctx_by_post[pid][0], clip_text=ctx_by_post[pid][1], max_chars=prov.reply_max_chars)
        for pid, rc in found
    ]
    results, notes = engine.process(ctx, items, st) if items else ({}, [])
    ctx.progress(95)

    created = auto_replied = auto_hidden = 0
    with session_scope() as s:
        a = s.get(Account, aid, with_for_update=True)
        for pid, rc in found:
            r = results.get(rc.remote_id)
            cm = Comment(
                account_id=aid,
                post_id=pid,
                remote_id=rc.remote_id,
                author=rc.author[:200],
                message=rc.text,
                commented_at=rc.created_at,
                category=CommentCategory(r.category if r else "other"),
                category_by=r.by if r else "rules",
                draft=r.draft if r else "",
                draft_by=r.by if r and r.draft else "",
            )
            s.add(cm)
            s.flush()
            created += 1
            if cm.category == CommentCategory.spam and st.auto_hide_spam:
                cm.state = "done"
                queue.enqueue(s, HIDE_KIND, {"comment_id": str(cm.id), "hidden": True}, dedupe_key=f"comment:{cm.id}:hide")
                auto_hidden += 1
            elif cm.category.value in st.auto_reply_categories and cm.draft:
                cm.reply_text = cm.draft
                cm.reply_status = ReplyStatus.queued
                cm.reply_auto = True
                cm.state = "done"
                enqueue_reply(s, cm)
                auto_replied += 1
        a.comments_synced_at = now()
        if notes:
            a.last_error = None if not problems else a.last_error
    return {"new": created, "auto_replied": auto_replied, "auto_hidden": auto_hidden, "posts": len(post_info), "skipped_posts": problems, "notes": notes}


def _mark_reconnect(aid: uuid.UUID, msg: str) -> None:
    with session_scope() as s:
        a = s.get(Account, aid, with_for_update=True)
        a.status = AccountStatus.reconnect
        a.last_error = msg


# ---------- replies ----------


def enqueue_reply(s: Session, cm: Comment, delay_s: float = 0) -> None:
    # unique key per attempt so a running job can schedule the next one
    queue.enqueue(s, REPLY_KIND, {"comment_id": str(cm.id)}, dedupe_key=f"comment:{cm.id}:reply:{cm.reply_attempts}:{int(time.time())}", run_after=now() + timedelta(seconds=delay_s), priority=30, max_attempts=2)


def run_reply(ctx: JobContext) -> dict:
    cid = uuid.UUID(ctx.payload["comment_id"])
    with session_scope() as s:
        cm = s.get(Comment, cid, with_for_update=True)
        if cm is None or cm.reply_status != ReplyStatus.queued:
            return {"skipped": "not queued"}
        a = s.get(Account, cm.account_id)
        if a.status != AccountStatus.connected:
            cm.error = f"Waiting: the account is {a.status.value}."
            enqueue_reply(s, cm, 3600)
            return {"waiting": "account"}
        ws = s.get(Workspace, a.workspace_id)
        st = EngageSettings.from_workspace(ws.settings if ws else {})
        hour_ago = now() - timedelta(hours=1)
        sent_last_hour = s.scalar(
            select(func.count()).select_from(Comment).where(Comment.account_id == a.id, or_(Comment.replied_at >= hour_ago, Comment.reply_status == ReplyStatus.sending))
        )
        if sent_last_hour >= st.replies_per_hour:
            cm.error = f"Waiting: {st.replies_per_hour} replies per hour limit reached for {a.handle}."
            enqueue_reply(s, cm, 600)
            return {"waiting": "rate limit"}
        post = s.get(Post, cm.post_id) if cm.post_id else None
        prov = provider_for(a.platform.value, a.connection)
        text = cm.reply_text.strip()[: prov.reply_max_chars]
        args = (a.id, a.remote_id or "", post.remote_id if post else "", cm.remote_id, text)
        cm.reply_status = ReplyStatus.sending
        cm.reply_attempts += 1
        cm.error = None
        attempt = cm.reply_attempts
    aid, remote_id, post_rid, comment_rid, text = args
    result = err = None
    try:
        app, tokens = fresh_tokens(aid)
        result = prov.reply(app, tokens, remote_id, post_rid, comment_rid, text)
    except (AuthExpired, RetryableError, PermanentError, Ambiguous) as e:
        err = e
    except Exception as e:  # unexpected: the reply may exist
        log.exception("reply failed unexpectedly for %s", cid)
        err = Ambiguous(str(e), user_message="Something unexpected happened while replying; check the comment on the platform.")
    with session_scope() as s:
        cm = s.get(Comment, cid, with_for_update=True)
        if result is not None:
            cm.reply_status = ReplyStatus.sent
            cm.reply_remote_id = str(result)
            cm.replied_at = now()
            cm.state = "done"
            return {"sent": result}
        msg = err.user_message if isinstance(err, ClipstarError) else str(err)
        cm.error = msg
        if isinstance(err, AuthExpired):
            cm.reply_status = ReplyStatus.failed
            a = s.get(Account, cm.account_id, with_for_update=True)
            a.status = AccountStatus.reconnect
            a.last_error = msg
        elif isinstance(err, Ambiguous):
            cm.reply_status = ReplyStatus.unknown
        elif isinstance(err, RetryableError) and attempt < MAX_REPLY_TRIES:
            cm.reply_status = ReplyStatus.queued
            enqueue_reply(s, cm, 60 * 3**attempt)
        else:
            cm.reply_status = ReplyStatus.failed
            cm.state = "open"  # back in the inbox for the creator
        return {"outcome": cm.reply_status.value, "error": msg}


def run_hide(ctx: JobContext) -> dict:
    cid = uuid.UUID(ctx.payload["comment_id"])
    hidden = bool(ctx.payload.get("hidden", True))
    with session_scope() as s:
        cm = s.get(Comment, cid)
        if cm is None:
            return {"skipped": True}
        a = s.get(Account, cm.account_id)
        aid, platform, connection, remote_id, crid = a.id, a.platform.value, a.connection, a.remote_id or "", cm.remote_id
    try:
        app, tokens = fresh_tokens(aid)
        provider_for(platform, connection).hide(app, tokens, remote_id, crid, hidden)
    except AuthExpired as e:
        _mark_reconnect(aid, e.user_message)
        with session_scope() as s:
            s.get(Comment, cid).error = e.user_message
        return {"error": "reconnect"}
    except PermanentError as e:
        with session_scope() as s:
            cm = s.get(Comment, cid)
            cm.error = e.user_message
            cm.state = "open"
        return {"error": e.user_message}
    with session_scope() as s:
        cm = s.get(Comment, cid)
        cm.hidden = hidden
        cm.error = None
        cm.state = "done" if hidden else cm.state
    return {"hidden": hidden}


def register_handlers() -> None:
    register(SYNC_KIND, Handler(run=run_sync))
    register(REPLY_KIND, Handler(run=run_reply))
    register(HIDE_KIND, Handler(run=run_hide))
