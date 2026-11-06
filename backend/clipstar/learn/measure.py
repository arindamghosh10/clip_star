"""Measure: stats snapshots for each published post (1 h, 1 day, 3 days, 7 days) and daily follower counts."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db import session_scope
from ..errors import PermanentError, RetryableError
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..models import Account, AccountMetric, AccountStatus, Clip, Post, PostMetric, PostStatus
from ..platforms.base import Ambiguous, AuthExpired
from ..platforms.registry import provider_for
from ..publishing.service import fresh_tokens

log = logging.getLogger("clipstar.measure")

SCHEDULE_H = [1, 24, 72, 168]  # hours after publishing
FOLLOWERS_EVERY = timedelta(hours=24)
KIND = "metrics.collect"
FIELDS = ("views", "likes", "comments", "shares", "saves", "watch_pct", "avg_watch_s", "follows")


def now() -> datetime:
    return datetime.now(timezone.utc)


def due(p: Post, at: datetime) -> bool:
    return p.published_at is not None and p.metrics_step < len(SCHEDULE_H) and p.published_at + timedelta(hours=SCHEDULE_H[p.metrics_step]) <= at


def dispatch_metrics() -> int:
    at = now()
    accounts: set[uuid.UUID] = set()
    with session_scope() as s:
        posts = s.scalars(
            select(Post).where(Post.status == PostStatus.published, Post.metrics_step < len(SCHEDULE_H), Post.published_at >= at - timedelta(hours=SCHEDULE_H[-1] + 48), Post.remote_id.is_not(None))
        )
        for p in posts:
            if due(p, at):
                accounts.add(p.account_id)
        for a in s.scalars(select(Account).where(Account.status == AccountStatus.connected)):
            if a.metrics_at is None or a.metrics_at < at - FOLLOWERS_EVERY:
                if s.scalar(select(Post.id).where(Post.account_id == a.id, Post.status == PostStatus.published).limit(1)):
                    accounts.add(a.id)
        for aid in accounts:
            a = s.get(Account, aid)
            if a and provider_for(a.platform.value, a.connection).metrics_supported:
                queue.enqueue(s, KIND, {"account_id": str(aid)}, dedupe_key=f"metrics:{aid}", priority=80)
    return len(accounts)


def _hints(c: Clip | None, variant: str) -> dict:
    if c is None:
        return {}
    v = next((x for x in (c.variants or []) if x.get("id") == variant), {})
    return {"hook_text": v.get("hook") or c.hook, "duration_s": c.end_s - c.start_s, "variant": variant}


def run_collect(ctx: JobContext) -> dict:
    aid = uuid.UUID(ctx.payload["account_id"])
    at = now()
    with session_scope() as s:
        a = s.get(Account, aid)
        if a is None or a.status != AccountStatus.connected:
            return {"skipped": True}
        prov = provider_for(a.platform.value, a.connection)
        posts = [p for p in s.scalars(select(Post).where(Post.account_id == aid, Post.status == PostStatus.published, Post.remote_id.is_not(None))) if due(p, at)]
        clips = {c.id: c for c in s.scalars(select(Clip).where(Clip.id.in_([p.clip_id for p in posts])))} if posts else {}
        work = [(p.id, p.remote_id, p.published_at, p.metrics_step, _hints(clips.get(p.clip_id), p.variant)) for p in posts]
        followers_due = a.metrics_at is None or a.metrics_at < at - FOLLOWERS_EVERY
        remote_id = a.remote_id or str(a.id)
    try:
        app, tokens = fresh_tokens(aid)
    except AuthExpired as e:
        with session_scope() as s:
            acc = s.get(Account, aid)
            acc.status, acc.last_error = AccountStatus.reconnect, e.user_message
        return {"error": "reconnect"}

    results = {}
    for pid, rid, published, step, hints in work:
        try:
            results[pid] = ("ok", prov.post_metrics(app, tokens, remote_id, rid, published, hints))
        except RetryableError:
            raise
        except AuthExpired as e:
            with session_scope() as s:
                acc = s.get(Account, aid)
                acc.status, acc.last_error = AccountStatus.reconnect, e.user_message
            return {"error": "reconnect"}
        except (PermanentError, Ambiguous) as e:
            results[pid] = ("gone", str(e))  # e.g. deleted on the platform: stop asking
    followers = None
    if followers_due:
        try:
            followers = prov.account_followers(app, tokens, remote_id)
        except RetryableError:
            raise
        except Exception as e:  # followers are a nice-to-have
            log.info("followers unavailable for %s: %s", aid, e)

    with session_scope() as s:
        for pid, rid, published, step, _ in work:
            kind, data = results.get(pid, ("skip", None))
            p = s.get(Post, pid, with_for_update=True)
            hours = (at - published).total_seconds() / 3600
            passed = sum(1 for h in SCHEDULE_H if h <= hours)
            if kind == "gone":
                p.metrics_step = len(SCHEDULE_H)
                p.metrics = {**(p.metrics or {}), "_error": "Stats unavailable: the post may have been removed."}
                continue
            if kind != "ok":
                continue
            clean = {k: data.get(k) for k in FIELDS if data.get(k) is not None}
            s.add(PostMetric(post_id=pid, hours=round(hours, 2), raw=data, **clean))
            p.metrics = {**{k: v for k, v in (p.metrics or {}).items() if not k.startswith("_")}, **clean, "hours": round(hours, 1), "updated_at": at.isoformat()}
            p.metrics_step = max(step + 1, passed)
        acc = s.get(Account, aid, with_for_update=True)
        if followers_due:
            acc.metrics_at = at
            if followers is not None:
                s.add(AccountMetric(account_id=aid, followers=followers))
    return {"posts": len(work), "followers": followers}


def register_handlers() -> None:
    register(KIND, Handler(run=run_collect))
