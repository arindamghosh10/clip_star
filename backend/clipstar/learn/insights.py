"""Learn: turn post stats into insights, ideas and a per-creator scoring model.

Principles:
- Compare like with like: each post's views are divided by its account's typical (median) views,
  so a big account doesn't drown out a small one.
- Only say something when there is enough data: every insight names its sample size, and
  differences under 20% or with fewer than MIN_N posts per side are not reported.
- The scoring model is only switched on if it predicts held-out posts better than the built-in rules.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Clip, Comment, CommentCategory, Post, PostStatus, Video, VideoStatus, Workspace

MIN_N = 5
MIN_LIFT = 0.2
FEATURES = ["hook", "energy", "peaks", "complete", "length_fit", "words_per_s", "cuts", "number_hook", "question_hook"]


@dataclass
class Row:
    post_id: str
    account_id: str
    platform: str
    practice: bool
    clip_id: str
    clip_title: str
    video_id: str
    views: float
    watch_pct: float | None
    shares: float | None
    follows: float | None
    duration: float
    hook: str
    variant: str
    caption_style: str
    hour: int
    features: dict
    heuristic: float
    rel: float = 1.0  # views relative to the account's median


def hook_type(h: str) -> str:
    t = (h or "").lower()
    if re.search(r"\d|\$|\b(one|two|three|four|five|ten|forty|fifty|hundred|thousand|million)\b", t):
        return "number"
    if t.strip().endswith("?") or re.match(r"^(how|why|what|when|which|who|can|do|does|is|are|should)\b", t):
        return "question"
    return "statement"


def load_rows(s: Session, ws_id: uuid.UUID, since: datetime | None = None) -> list[Row]:
    q = (
        select(Post, Account, Clip)
        .join(Account, Account.id == Post.account_id)
        .join(Clip, Clip.id == Post.clip_id)
        .where(Account.workspace_id == ws_id, Post.status == PostStatus.published, Post.published_at.is_not(None))
    )
    if since:
        q = q.where(Post.published_at >= since)
    rows: list[Row] = []
    for p, a, c in s.execute(q):
        m = p.metrics or {}
        if m.get("views") is None:
            continue
        v = next((x for x in (c.variants or []) if x.get("id") == p.variant), {})
        hook = v.get("hook") or c.hook or c.title
        feats = dict((c.meta or {}).get("features") or {})
        feats["number_hook"] = 1.0 if hook_type(hook) == "number" else 0.0
        feats["question_hook"] = 1.0 if hook_type(hook) == "question" else 0.0
        rows.append(
            Row(
                post_id=str(p.id), account_id=str(a.id), platform=a.platform.value, practice=a.connection == "simulated",
                clip_id=str(c.id), clip_title=c.title, video_id=str(c.video_id),
                views=float(m["views"]), watch_pct=m.get("watch_pct"), shares=m.get("shares"), follows=m.get("follows"),
                duration=c.end_s - c.start_s, hook=hook, variant=p.variant, caption_style=v.get("caption_style", "bold-pop"),
                hour=p.published_at.astimezone(ZoneInfo(a.timezone)).hour,
                features=feats, heuristic=float((c.meta or {}).get("heuristic") or c.score),
            )
        )
    by_acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_acc[r.account_id].append(r.views)
    overall = median([r.views for r in rows]) if rows else 1
    for r in rows:
        base = median(by_acc[r.account_id]) if len(by_acc[r.account_id]) >= 3 else overall
        r.rel = r.views / max(base, 1.0)
    return rows


def _length_bucket(d: float) -> str:
    return "under 25 s" if d < 25 else "25-35 s" if d < 35 else "35-50 s" if d <= 50 else "over 50 s"


def _time_bucket(h: int) -> str:
    return "mornings (6-12)" if 6 <= h < 12 else "afternoons (12-17)" if 12 <= h < 17 else "evenings (17-22)" if 17 <= h < 22 else "late night (22-6)"


DIMENSIONS = [
    ("length", "Clip length", lambda r: _length_bucket(r.duration)),
    ("hook", "Hook style", lambda r: {"number": "hooks with a number", "question": "question hooks", "statement": "statement hooks"}[hook_type(r.hook)]),
    ("captions", "Caption style", lambda r: "bold word-highlight captions" if r.caption_style == "bold-pop" else "clean boxed captions"),
    ("time", "Posting time", lambda r: _time_bucket(r.hour)),
    ("platform", "Platform", lambda r: r.platform),
]


def insights(rows: list[Row]) -> list[dict]:
    out: list[dict] = []
    if len(rows) < 2 * MIN_N:
        return out
    overall = median(r.rel for r in rows)
    for key, label, fn in DIMENSIONS:
        groups: dict[str, list[Row]] = defaultdict(list)
        for r in rows:
            groups[fn(r)].append(r)
        stats = {g: (median(x.rel for x in rs), len(rs), [x.watch_pct for x in rs if x.watch_pct is not None]) for g, rs in groups.items() if len(rs) >= MIN_N}
        if len(stats) < 2:
            continue
        best = max(stats, key=lambda g: stats[g][0])
        worst = min(stats, key=lambda g: stats[g][0])
        lift = stats[best][0] / max(overall, 1e-9) - 1
        drop = stats[worst][0] / max(overall, 1e-9) - 1
        if lift >= MIN_LIFT:
            w = stats[best][2]
            extra = f" and were watched {median(w):.0f}% through on average" if w else ""
            out.append({"kind": "do", "dimension": key, "title": f"{label}: {best}", "body": f"Posts with {best} got {lift * 100:.0f}% more views than your typical post{extra}.", "n": stats[best][1], "lift": round(lift, 2)})
        if drop <= -MIN_LIFT and worst != best:
            out.append({"kind": "avoid", "dimension": key, "title": f"{label}: {worst}", "body": f"Posts with {worst} got {abs(drop) * 100:.0f}% fewer views than your typical post.", "n": stats[worst][1], "lift": round(drop, 2)})
    # A/B: the same clip posted as both versions
    pairs = defaultdict(lambda: defaultdict(list))
    for r in rows:
        pairs[r.clip_id][r.variant].append(r.rel)
    both = [(median(v["A"]), median(v["B"])) for v in pairs.values() if v.get("A") and v.get("B")]
    if len(both) >= MIN_N:
        wins_a = sum(1 for a, b in both if a > b)
        share = wins_a / len(both)
        if share >= 0.7 or share <= 0.3:
            winner = "A" if share >= 0.7 else "B"
            out.append({"kind": "do", "dimension": "ab", "title": f"Version {winner} wins A/B tests", "body": f"Version {winner} did better in {max(wins_a, len(both) - wins_a)} of {len(both)} clips posted as both versions.", "n": len(both), "lift": round(abs(share - 0.5) * 2, 2)})
    out.sort(key=lambda x: -abs(x["lift"]))
    return out


_STOP = set("the a an and or but to of in on at for with is are was it this that you your my i me we our do does did can could would should will how what why when where which who about have has get just really so if not be there here they them than then also more like any some".split())


def ideas_from_comments(s: Session, ws_id: uuid.UUID, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    qs = list(
        s.scalars(
            select(Comment.message).join(Account, Account.id == Comment.account_id).where(Account.workspace_id == ws_id, Comment.category == CommentCategory.question, Comment.created_at >= since)
        )
    )
    words = Counter()
    for q in qs:
        seen = set()
        for w in re.findall(r"[a-z][a-z']{2,}", q.lower()):
            if w not in _STOP and w not in seen:
                seen.add(w)
                words[w] += 1
    return [{"topic": w, "questions": n, "body": f"{n} viewers asked questions mentioning \"{w}\". It could make a good next video."} for w, n in words.most_common(5) if n >= 3]


def reclip_candidates(s: Session, ws_id: uuid.UUID, model_active: bool) -> list[dict]:
    """Older ready videos that haven't been posted from recently: worth re-clipping with what we've learned."""
    since = datetime.now(timezone.utc) - timedelta(days=14)
    out = []
    for v in s.scalars(select(Video).where(Video.workspace_id == ws_id, Video.status == VideoStatus.ready, Video.created_at < since).order_by(Video.created_at.desc()).limit(10)):
        recent = s.scalar(select(Post.id).join(Clip, Clip.id == Post.clip_id).where(Clip.video_id == v.id, Post.published_at >= since).limit(1))
        if not recent:
            out.append({"video_id": str(v.id), "title": v.title, "reason": "Your learned scoring can pick new moments from it." if model_active else "No clips from it were posted in the last two weeks."})
    return out[:5]


# ---------- per-creator scoring ----------


def _matrix(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[float(r.features.get(f, 0.0) or 0.0) for f in FEATURES] for r in rows], dtype=float)
    y = np.log(np.array([max(r.rel, 1e-3) for r in rows], dtype=float))
    return X, y


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def _fit(X: np.ndarray, y: np.ndarray, lam: float = 1.0):
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    w = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return w, mu, sd, float(y.mean())


def train(rows: list[Row], min_posts: int = 20, min_clips: int = 8) -> dict:
    """Fit a ridge model on account-relative performance. Active only if it beats the built-in score on held-out posts."""
    clips = {r.clip_id for r in rows}
    status = {"n": len(rows), "clips": len(clips), "active": False, "trained_at": datetime.now(timezone.utc).isoformat()}
    if len(rows) < min_posts or len(clips) < min_clips:
        status["reason"] = f"Needs at least {min_posts} posts from {min_clips} clips with stats (has {len(rows)} from {len(clips)})."
        return status
    X, y = _matrix(rows)
    # cross-validated by clip, so the same clip never sits in both train and test
    order = sorted(clips)
    folds = [set(order[i::5]) for i in range(5)]
    preds = np.zeros(len(rows))
    for f in folds:
        te = np.array([r.clip_id in f for r in rows])
        if te.all() or not te.any():
            continue
        w, mu, sd, b = _fit(X[~te], y[~te])
        preds[te] = ((X[te] - mu) / sd) @ w + b
    model_corr = _spearman(preds, y)
    base_corr = _spearman(np.array([r.heuristic for r in rows]), y)
    w, mu, sd, b = _fit(X, y)
    fitted = ((X - mu) / sd) @ w
    status.update(
        weights=dict(zip(FEATURES, [round(float(x), 4) for x in w])),
        mean=[float(x) for x in mu], std=[float(x) for x in sd], pred_std=float(np.std(fitted) or 1.0),
        corr=round(model_corr, 3), baseline_corr=round(base_corr, 3),
    )
    if model_corr > 0.2 and model_corr > base_corr + 0.05:
        status["active"] = True
        top = sorted(status["weights"].items(), key=lambda kv: -abs(kv[1]))[:3]
        status["reason"] = "Predicts your results better than the built-in rules (" + ", ".join(f"{k} {'+' if v > 0 else '-'}" for k, v in top) + ")."
    else:
        status["reason"] = f"Not used yet: it didn't beat the built-in rules on held-out posts (model {model_corr:.2f} vs rules {base_corr:.2f})."
    return status


def learned_score(model: dict | None, feats: dict) -> float | None:
    """0-100 score from the learned model, or None if no active model."""
    if not model or not model.get("active"):
        return None
    x = np.array([float(feats.get(f, 0.0) or 0.0) for f in FEATURES])
    z = (x - np.array(model["mean"])) / np.array(model["std"])
    pred = float(z @ np.array([model["weights"][f] for f in FEATURES])) / max(model.get("pred_std", 1.0), 1e-6)
    return 100 / (1 + math.exp(-pred))


def retrain(s: Session, ws: Workspace) -> dict:
    status = train(load_rows(s, ws.id, since=datetime.now(timezone.utc) - timedelta(days=180)))
    ws.settings = {**(ws.settings or {}), "learned_model": status}
    return status
