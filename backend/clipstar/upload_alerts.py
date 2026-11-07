"""Tell the creator when a new long video appears on their own YouTube channel, so it can be clipped.

YouTube's API doesn't let apps download videos, so the alert asks for the original file
(or a Drive/Dropbox link). The first check only notes what's already there; nothing old is announced.
Our own Shorts (posted by clip_star) are ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .db import session_scope
from .jobs import queue

KIND = "youtube.uploads"
EVERY = timedelta(hours=1)


def now() -> datetime:
    return datetime.now(timezone.utc)


def dispatch() -> int:
    from .models import Account, AccountStatus, Platform

    n = 0
    with session_scope() as s:
        for a in s.scalars(select(Account).where(Account.platform == Platform.youtube, Account.status == AccountStatus.connected, Account.connection == "oauth")):
            last = (a.options or {}).get("uploads_checked_at")
            if last and datetime.fromisoformat(last) > now() - EVERY:
                continue
            queue.enqueue(s, KIND, {"account_id": str(a.id)}, dedupe_key=f"uploads:{a.id}", priority=90, max_attempts=2)
            n += 1
    return n


def run_check(ctx) -> dict:
    from .events import emit
    from .models import Account, Post
    from .notify import notify
    from .platforms.registry import provider_for
    from .publishing.service import fresh_tokens

    aid = uuid.UUID(ctx.payload["account_id"])
    with session_scope() as s:
        a = s.get(Account, aid)
        if a is None:
            return {"skipped": True}
        remote_id, platform, connection = a.remote_id, a.platform.value, a.connection
    app, tokens = fresh_tokens(aid)
    uploads = provider_for(platform, connection).latest_uploads(app, tokens, remote_id or "")
    with session_scope() as s:
        a = s.get(Account, aid, with_for_update=True)
        opts = dict(a.options or {})
        seen = set(opts.get("uploads_seen") or [])
        ours = set(s.scalars(select(Post.remote_id).where(Post.account_id == aid, Post.remote_id.is_not(None))))
        first_run = "uploads_seen" not in opts
        new = [u for u in uploads if u["id"] not in seen and u["id"] not in ours]
        if not first_run:
            for u in reversed(new):
                notify(s, a.workspace_id, "new_upload", f"New on YouTube: {u['title'] or 'a new video'}", f"{a.handle} published a new video. To clip it, add the original file (YouTube doesn't let apps download videos), or paste a Drive/Dropbox link.", "/videos", dedupe=f"upload:{u['id']}")
                emit(s, a.workspace_id, "youtube.new_upload", {"account_id": str(a.id), "video_id": u["id"], "title": u["title"], "url": f"https://www.youtube.com/watch?v={u['id']}", "published_at": u["published_at"]})
        opts["uploads_seen"] = list(dict.fromkeys([u["id"] for u in uploads] + list(seen)))[:50]
        opts["uploads_checked_at"] = now().isoformat()
        a.options = opts
    return {"new": 0 if first_run else len(new), "baseline": first_run}


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(KIND, Handler(run=run_check))
