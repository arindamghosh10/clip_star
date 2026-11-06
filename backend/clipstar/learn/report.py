"""Overview numbers and the weekly report (totals, top posts, insights, ideas, re-clip suggestions, model status)."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..models import Account, AccountMetric, Clip, Post, PostStatus, Report, Workspace
from . import insights as L

log = logging.getLogger("clipstar.report")

KIND = "learn.report"
EVERY = timedelta(days=7)
SUMS = ("views", "likes", "comments", "shares", "saves", "follows")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _published(s: Session, ws_id: uuid.UUID, start: datetime, end: datetime, account_id: uuid.UUID | None = None):
    q = (
        select(Post, Account, Clip)
        .join(Account, Account.id == Post.account_id)
        .join(Clip, Clip.id == Post.clip_id)
        .where(Account.workspace_id == ws_id, Post.status == PostStatus.published, Post.published_at >= start, Post.published_at < end)
    )
    if account_id:
        q = q.where(Post.account_id == account_id)
    return list(s.execute(q))


def totals(rows) -> dict:
    t = {k: 0 for k in SUMS}
    watch = []
    measured = 0
    practice = 0
    for p, a, _ in rows:
        m = p.metrics or {}
        if a.connection == "simulated":
            practice += 1
        if m.get("views") is None:
            continue
        measured += 1
        for k in SUMS:
            if isinstance(m.get(k), (int, float)):
                t[k] += m[k]
        if isinstance(m.get("watch_pct"), (int, float)):
            watch.append(m["watch_pct"])
    t["posts"] = len(rows)
    t["measured"] = measured
    t["practice_posts"] = practice
    t["watch_pct"] = round(sum(watch) / len(watch), 1) if watch else None
    return t


def _follower_gain(s: Session, ws_id: uuid.UUID, start: datetime, end: datetime) -> int | None:
    """Followers at the end of the period minus at the start, summed over accounts with readings at both ends."""
    gain, any_ = 0, False
    for (aid,) in s.execute(select(Account.id).where(Account.workspace_id == ws_id)):
        vals = list(s.scalars(select(AccountMetric.followers).where(AccountMetric.account_id == aid, AccountMetric.at >= start, AccountMetric.at < end, AccountMetric.followers.is_not(None)).order_by(AccountMetric.at)))
        if len(vals) >= 2:  # one reading can't show a change
            gain += vals[-1] - vals[0]
            any_ = True
    return gain if any_ else None


def _post_out(p: Post, a: Account, c: Clip, rel: float | None = None) -> dict:
    m = p.metrics or {}
    return {
        "post_id": str(p.id), "clip_id": str(c.id), "clip_title": c.title, "video_id": str(c.video_id), "variant": p.variant,
        "account_id": str(a.id), "account": a.handle, "platform": a.platform.value, "practice": a.connection == "simulated",
        "published_at": p.published_at.isoformat() if p.published_at else None, "remote_url": p.remote_url,
        "views": m.get("views"), "likes": m.get("likes"), "comments": m.get("comments"), "shares": m.get("shares"),
        "watch_pct": m.get("watch_pct"), "follows": m.get("follows"), "rel": round(rel, 2) if rel is not None else None,
    }


def overview(s: Session, ws: Workspace, days: int = 7, account_id: uuid.UUID | None = None) -> dict:
    end = now()
    start = end - timedelta(days=days)
    cur = _published(s, ws.id, start, end, account_id)
    prev = _published(s, ws.id, start - timedelta(days=days), start, account_id)

    # daily series by publish day (each post's latest stats)
    series: dict[str, dict] = {}
    for d in range(days):
        day = (start + timedelta(days=d + 1)).date().isoformat()
        series[day] = {"date": day, "views": 0, "posts": 0}
    by_platform: dict[str, dict] = defaultdict(lambda: {"posts": 0, "views": 0})
    by_account: dict[str, dict] = {}
    for p, a, c in cur:
        v = (p.metrics or {}).get("views") or 0
        day = p.published_at.date().isoformat()
        if day in series:
            series[day]["views"] += v
            series[day]["posts"] += 1
        by_platform[a.platform.value]["posts"] += 1
        by_platform[a.platform.value]["views"] += v
        ba = by_account.setdefault(str(a.id), {"account_id": str(a.id), "handle": a.handle, "platform": a.platform.value, "practice": a.connection == "simulated", "posts": 0, "views": 0})
        ba["posts"] += 1
        ba["views"] += v

    rows = L.load_rows(s, ws.id, since=start)
    rel = {r.post_id: r.rel for r in rows}
    ranked = sorted((x for x in cur if (x[0].metrics or {}).get("views") is not None), key=lambda x: -((x[0].metrics or {}).get("views") or 0))
    top = [_post_out(p, a, c, rel.get(str(p.id))) for p, a, c in ranked[:5]]

    t, pt = totals(cur), totals(prev)
    t["follower_gain"] = _follower_gain(s, ws.id, start, end) if account_id is None else None
    pending = s.scalar(
        select(func.count(Post.id)).join(Account, Account.id == Post.account_id).where(Account.workspace_id == ws.id, Post.status.in_([PostStatus.scheduled, PostStatus.held]))
    )
    return {
        "days": days, "start": start.isoformat(), "end": end.isoformat(),
        "totals": t, "previous": pt,
        "series": list(series.values()),
        "by_platform": [{"platform": k, **v} for k, v in sorted(by_platform.items(), key=lambda kv: -kv[1]["views"])],
        "by_account": sorted(by_account.values(), key=lambda x: -x["views"]),
        "top_posts": top,
        "scheduled": pending or 0,
        "practice_only": t["posts"] > 0 and t["practice_posts"] == t["posts"],
    }


def learn_view(s: Session, ws: Workspace) -> dict:
    rows = L.load_rows(s, ws.id, since=now() - timedelta(days=90))
    model = (ws.settings or {}).get("learned_model")
    return {
        "n": len(rows),
        "practice": sum(1 for r in rows if r.practice),
        "insights": L.insights(rows),
        "ideas": L.ideas_from_comments(s, ws.id),
        "reclip": L.reclip_candidates(s, ws.id, bool(model and model.get("active"))),
        "model": model,
        "min_n": L.MIN_N,
    }


def _pct(a: float, b: float) -> str:
    if not b:
        return ""
    d = (a - b) / b * 100
    return f" ({'+' if d >= 0 else ''}{d:.0f}% vs the week before)"


def build_report(s: Session, ws: Workspace) -> Report:
    end = now()
    start = end - EVERY
    model = L.retrain(s, ws)
    ov = overview(s, ws, days=7)
    lv = learn_view(s, ws)
    t, pt = ov["totals"], ov["previous"]
    parts = [f"{t['posts']} posts published, {int(t['views']):,} views{_pct(t['views'], pt['views'])}."]
    if t.get("follower_gain") is not None:
        parts.append(f"Followers {'+' if t['follower_gain'] >= 0 else ''}{t['follower_gain']:,}.")
    if ov["top_posts"]:
        tp = ov["top_posts"][0]
        parts.append(f"Best post: \"{tp['clip_title']}\" on {tp['account']} ({int(tp['views'] or 0):,} views).")
    if lv["insights"]:
        parts.append(f"Top finding: {lv['insights'][0]['body']}")
    if model.get("active"):
        parts.append("Your learned scoring is on and helps pick new moments.")
    if ov["practice_only"]:
        parts.append("All of these are practice posts with made-up numbers.")
    rep = Report(
        workspace_id=ws.id, period_start=start, period_end=end, summary=" ".join(parts),
        data={"overview": ov, "insights": lv["insights"], "ideas": lv["ideas"], "reclip": lv["reclip"], "model": model, "n": lv["n"]},
    )
    s.add(rep)
    s.flush()
    return rep


def run_report(ctx: JobContext) -> dict:
    with session_scope() as s:
        ws = s.get(Workspace, uuid.UUID(ctx.payload["workspace_id"]), with_for_update=True)
        if ws is None:
            return {"skipped": True}
        rep = build_report(s, ws)
        return {"report_id": str(rep.id)}


def dispatch_reports() -> int:
    """Queue a weekly report for each workspace that has published something and has no report in the last 7 days."""
    n = 0
    with session_scope() as s:
        for ws in s.scalars(select(Workspace)):
            last = s.scalar(select(func.max(Report.created_at)).where(Report.workspace_id == ws.id))
            if last and last > now() - EVERY:
                continue
            has = s.scalar(select(Post.id).join(Account, Account.id == Post.account_id).where(Account.workspace_id == ws.id, Post.status == PostStatus.published).limit(1))
            if has:
                queue.enqueue(s, KIND, {"workspace_id": str(ws.id)}, dedupe_key=f"report:{ws.id}", priority=90)
                n += 1
    return n


def register_handlers() -> None:
    register(KIND, Handler(run=run_report))
