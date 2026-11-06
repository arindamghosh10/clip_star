import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from clipstar.db import session_scope
from clipstar.learn import insights as L
from clipstar.learn import measure, report
from clipstar.models import (
    Account,
    AccountMetric,
    Asset,
    Batch,
    BatchStatus,
    Clip,
    ClipStatus,
    Job,
    Post,
    PostMetric,
    PostStatus,
    Report,
    Stage,
    Video,
    VideoStatus,
    Workspace,
)
from clipstar.pipeline import register_all
from clipstar.pipeline.moments import Candidate, MomentSettings, blend_learned
from clipstar.platforms import util
from clipstar.platforms.base import App, Tokens
from clipstar.platforms.http import set_transport
from clipstar.platforms.meta import Facebook, Instagram, Threads
from clipstar.platforms.pinterest import Pinterest
from clipstar.platforms.tiktok import TikTok
from clipstar.platforms.x import X
from clipstar.platforms.youtube import YouTube
from clipstar.worker import Worker

from .conftest import drain

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()


def practice_account(client, handle="@maya", platform="instagram"):
    return client.post("/api/accounts", json={"platform": platform, "handle": handle}).json()


def make_posts(acc_id, specs, hours_ago=200, with_metrics=False):
    """specs: list of (hook, duration, variant). Returns post ids."""
    ids = []
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="ep.mp4", duration_s=600)
        s.add(v)
        s.flush()
        b = Batch(workspace_id=ws.id, name="B", status=BatchStatus.running)
        s.add(b)
        s.flush()
        for k, (hook, dur, variant) in enumerate(specs):
            c = Clip(
                video_id=v.id, title=f"Clip {k}", hook=hook, start_s=0, end_s=dur, score=60, status=ClipStatus.approved,
                variants=[{"id": "A", "hook": hook, "caption_style": "bold-pop"}, {"id": "B", "hook": hook, "caption_style": "clean"}],
                meta={"features": {"hook": 0.5, "energy": 0.5, "peaks": 1, "complete": 1.0, "length_fit": 1.0 if 35 <= dur <= 50 else 0.3, "words_per_s": 2.5, "cuts": 2}, "heuristic": 60},
            )
            s.add(c)
            s.flush()
            at = NOW - timedelta(hours=hours_ago + k * 0.1)
            p = Post(batch_id=b.id, account_id=acc_id, clip_id=c.id, variant=variant, caption="x", scheduled_at=at, status=PostStatus.published, published_at=at, remote_id=f"sim-{acc_id}-{k}")
            if with_metrics is not False:
                p.metrics = with_metrics(hook, dur, variant)
                p.metrics_step = len(measure.SCHEDULE_H)
            s.add(p)
            s.flush()
            ids.append(p.id)
    return ids


# ---------- measure ----------


def test_due_schedule():
    p = Post(published_at=NOW - timedelta(hours=2), metrics_step=0)
    assert measure.due(p, NOW)
    p.metrics_step = 1
    assert not measure.due(p, NOW)  # next check at 24 h
    assert measure.due(p, NOW + timedelta(hours=23))
    p.metrics_step = len(measure.SCHEDULE_H)
    assert not measure.due(p, NOW + timedelta(days=30))


def test_collect_practice_posts_and_followers(client):
    acc = practice_account(client)
    ids = make_posts(acc["id"], [("3 rent traps", 40, "A"), ("Here is a tip", 20, "B")], hours_ago=30)
    assert measure.dispatch_metrics() == 1
    assert measure.dispatch_metrics() == 1  # same account: deduped, one job
    drain(Worker("w"), limit=5)
    with session_scope() as s:
        posts = {p.id: p for p in s.scalars(select(Post).where(Post.id.in_(ids)))}
        a, b = posts[ids[0]], posts[ids[1]]
        assert a.metrics["views"] > b.metrics["views"]  # practice stats favour number hooks and 35-50 s
        assert a.metrics_step == 2  # 1 h and 24 h both passed: one snapshot, step jumps ahead
        assert s.scalar(select(PostMetric.id).where(PostMetric.post_id == a.id))
        assert s.scalar(select(AccountMetric.followers).where(AccountMetric.account_id == acc["id"])) > 0
    # nothing more due right now
    assert measure.dispatch_metrics() == 0


def test_collect_skips_disconnected_and_marks_gone(client, monkeypatch):
    acc = practice_account(client)
    [pid] = make_posts(acc["id"], [("hello", 40, "A")], hours_ago=2)
    from clipstar.errors import PermanentError
    from clipstar.platforms.simulated import Simulated

    def gone(*a, **k):
        raise PermanentError("404", user_message="not found")

    monkeypatch.setattr(Simulated, "post_metrics", gone)
    measure.dispatch_metrics()
    drain(Worker("w"), limit=5)
    with session_scope() as s:
        p = s.get(Post, pid)
        assert p.metrics_step == len(measure.SCHEDULE_H) and "_error" in p.metrics
        job = s.scalar(select(Job).where(Job.kind == measure.KIND))
        assert job.status.value == "succeeded"


# ---------- platform metric parsers ----------

APP = App("cid", "secret")
TOK = Tokens("TOKEN")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(util, "sleep", lambda s: None)

    def install(routes):
        def handler(req):
            for m, frag, fn in routes:
                if req.method == m and frag in str(req.url):
                    return fn(req)
            return httpx.Response(404, json={"error": {"message": "no route"}})

        set_transport(httpx.MockTransport(handler))

    yield install
    set_transport(None)


def J(d, status=200):
    return lambda r: httpx.Response(status, json=d)


def test_metrics_parsers(fake):
    pub = NOW - timedelta(days=1)
    fake(
        [
            ("GET", "youtubeanalytics", J({"columnHeaders": [{"name": "averageViewPercentage"}, {"name": "averageViewDuration"}, {"name": "shares"}, {"name": "subscribersGained"}], "rows": [[71.5, 28, 9, 4]]})),
            ("GET", "/youtube/v3/videos", J({"items": [{"statistics": {"viewCount": "1200", "likeCount": "80", "commentCount": "7"}}]})),
            ("GET", "/youtube/v3/channels", J({"items": [{"statistics": {"subscriberCount": "5400"}}]})),
            ("GET", "/ig1/insights", J({"data": [{"name": "views", "values": [{"value": 900}]}, {"name": "likes", "values": [{"value": 50}]}, {"name": "saved", "total_value": {"value": 3}}, {"name": "ig_reels_avg_watch_time", "values": [{"value": 12500}]}]})),
            ("GET", "/fb1/video_insights", J({"data": [{"name": "blue_reels_play_count", "values": [{"value": 300}]}]})),
            ("GET", "/fb1?", J({"likes": {"summary": {"total_count": 12}}, "comments": {"summary": {"total_count": 2}}})),
            ("GET", "/th1/insights", J({"data": [{"name": "views", "values": [{"value": 40}]}, {"name": "reposts", "total_value": {"value": 2}}, {"name": "quotes", "total_value": {"value": 1}}]})),
            ("GET", "/tweets/x1", J({"data": {"public_metrics": {"impression_count": 5000, "like_count": 30, "reply_count": 4, "retweet_count": 5, "quote_count": 1, "bookmark_count": 2}}})),
            ("POST", "/video/query/", J({"data": {"videos": [{"view_count": 777, "like_count": 70, "share_count": 9}]}, "error": {"code": "ok"}})),
            ("GET", "/pins/p1/analytics", J({"all": {"summary_metrics": {"IMPRESSION": 400, "VIDEO_MRC_VIEW": 250, "SAVE": 6, "VIDEO_AVG_WATCH_TIME": 4000}}})),
        ]
    )
    yt = YouTube().post_metrics(APP, TOK, "chan", "v1", pub)
    assert yt == {"views": 1200, "likes": 80, "comments": 7, "watch_pct": 71.5, "avg_watch_s": 28, "shares": 9, "follows": 4}
    assert YouTube().account_followers(APP, TOK, "chan") == 5400
    ig = Instagram().post_metrics(APP, TOK, "u", "ig1", pub)
    assert ig["views"] == 900 and ig["saves"] == 3 and ig["avg_watch_s"] == 12.5
    fb = Facebook().post_metrics(APP, TOK, "page", "fb1", pub)
    assert fb["views"] == 300 and fb["likes"] == 12 and fb["comments"] == 2
    th = Threads().post_metrics(APP, TOK, "u", "th1", pub)
    assert th["views"] == 40 and th["shares"] == 3
    x = X().post_metrics(APP, TOK, "u", "x1", pub)
    assert x["views"] == 5000 and x["shares"] == 6 and x["saves"] == 2
    tt = TikTok().post_metrics(APP, TOK, "u", "t1", pub)
    assert tt["views"] == 777 and tt["shares"] == 9
    pin = Pinterest().post_metrics(APP, TOK, "u", "p1", pub)
    assert pin["views"] == 250 and pin["saves"] == 6 and pin["avg_watch_s"] == 4


def test_youtube_metrics_without_analytics(fake):
    fake([("GET", "/youtube/v3/videos", J({"items": [{"statistics": {"viewCount": "10"}}]}))])  # analytics 404s
    assert YouTube().post_metrics(APP, TOK, "chan", "v1", NOW)["views"] == 10


# ---------- learn ----------


def synthetic(hook, dur, variant):
    rnd = random.Random(hash((hook, dur, variant)) & 0xFFFF)
    v = 1000 * (2.0 if any(ch.isdigit() for ch in hook) else 1.0) * (1.0 + rnd.random() * 0.2)
    return {"views": int(v), "watch_pct": 50.0}


def test_insights_need_enough_data_and_find_the_pattern(client):
    acc = practice_account(client)
    make_posts(acc["id"], [("3 traps", 40, "A"), ("a tip", 40, "A"), ("5 tips", 40, "A"), ("my story", 40, "A")], with_metrics=synthetic)
    with session_scope() as s:
        ws = s.query(Workspace).one()
        assert L.insights(L.load_rows(s, ws.id)) == []  # 4 posts: too few to say anything
    hooks = [f"{n} rent traps" for n in range(8)] + [f"tip about leases {k}" for k in "abcdefgh"]
    make_posts(acc["id"], [(h, 40, "A") for h in hooks], with_metrics=synthetic)
    with session_scope() as s:
        ws = s.query(Workspace).one()
        rows = L.load_rows(s, ws.id)
        found = L.insights(rows)
    hook_do = [i for i in found if i["dimension"] == "hook" and i["kind"] == "do"]
    assert hook_do and "number" in hook_do[0]["title"] and hook_do[0]["n"] >= L.MIN_N
    assert not any(i["dimension"] == "length" for i in found)  # all 40 s: nothing to compare


def test_relative_views_compare_accounts_fairly(client):
    big = practice_account(client, "@big")
    small = practice_account(client, "@small")
    make_posts(big["id"], [(f"x{k}", 40, "A") for k in range(4)], with_metrics=lambda *a: {"views": 100000})
    make_posts(small["id"], [(f"y{k}", 40, "A") for k in range(4)], with_metrics=lambda *a: {"views": 100})
    with session_scope() as s:
        rows = L.load_rows(s, s.query(Workspace).one().id)
    assert {round(r.rel, 2) for r in rows} == {1.0}


def test_training_gate():
    def row(i, feats, rel, heur):
        return L.Row(post_id=str(i), account_id="a", platform="instagram", practice=True, clip_id=f"c{i}", clip_title="", video_id="v", views=rel * 100, watch_pct=None, shares=None, follows=None, duration=40, hook="", variant="A", caption_style="bold-pop", hour=12, features=feats, heuristic=heur, rel=rel)

    assert not L.train([row(i, {}, 1, 50) for i in range(5)])["active"]  # too few
    rnd = random.Random(1)
    rows = []
    for i in range(60):
        e = rnd.random()
        rows.append(row(i, {"energy": e, "hook": rnd.random()}, math_exp(2 * e + rnd.gauss(0, 0.1)), heur=rnd.random() * 100))
    st = L.train(rows)
    assert st["active"] and st["weights"]["energy"] > 0 and st["corr"] > st["baseline_corr"]
    hi = L.learned_score(st, {"energy": 0.9, "hook": 0.5})
    lo = L.learned_score(st, {"energy": 0.1, "hook": 0.5})
    assert 0 <= lo < hi <= 100
    # when the built-in score already explains it, the model stays off
    rows2 = [row(r.post_id, r.features, r.rel, heur=r.features["energy"] * 100) for r in rows]
    assert not L.train(rows2)["active"]
    assert L.learned_score(None, {}) is None


def math_exp(x):
    import math

    return math.exp(x)


def test_learned_blend_respects_penalties():
    model = {"active": True, "weights": {f: 0.0 for f in L.FEATURES} | {"energy": 1.0}, "mean": [0.0] * len(L.FEATURES), "std": [1.0] * len(L.FEATURES), "pred_std": 0.2}
    c = Candidate(0, 1, 0, 40, score=50, heuristic=50, reason="x", features={"energy": 1.0})
    blend_learned(c, model)
    assert c.score > 50 and c.heuristic == 50 and "best performers" in c.reason
    c2 = Candidate(0, 1, 0, 40, score=20, heuristic=20, reason="x", features={"energy": 1.0, "housekeeping": 1})
    blend_learned(c2, model)
    assert c2.score <= 20  # intros never get boosted
    assert MomentSettings.from_workspace({"learned_model": {"active": False}}).learned_model is None
    assert MomentSettings.from_workspace({"learned_model": model}).learned_model is model
    bad = Candidate(0, 1, 0, 40, score=50, features={})
    blend_learned(bad, {"active": True, "weights": {}, "mean": [], "std": []})  # broken model: ignored
    assert bad.score == 50


# ---------- API ----------


def test_overview_and_report(client):
    acc = practice_account(client)
    make_posts(acc["id"], [(f"{k} tips", 40, "A") for k in range(3)], hours_ago=30, with_metrics=lambda *a: {"views": 1000, "likes": 50, "watch_pct": 60.0})
    make_posts(acc["id"], [("old one", 40, "A")], hours_ago=24 * 9, with_metrics=lambda *a: {"views": 500})
    ov = client.get("/api/analytics/overview", params={"days": 7}).json()
    assert ov["totals"]["posts"] == 3 and ov["totals"]["views"] == 3000 and ov["previous"]["views"] == 500
    assert ov["practice_only"] and ov["top_posts"][0]["views"] == 1000 and len(ov["series"]) == 7
    assert ov["by_account"][0]["handle"] == "@maya"
    one = client.get("/api/analytics/overview", params={"account_id": acc["id"]}).json()
    assert one["totals"]["posts"] == 3
    am = client.get(f"/api/accounts/{acc['id']}/metrics", params={"days": 7}).json()
    assert am["supported"] and am["overview"]["totals"]["posts"] == 3

    lv = client.get("/api/analytics/learn").json()
    assert lv["n"] == 4 and lv["insights"] == []

    r = client.post("/api/reports")
    assert r.status_code == 201
    rep = r.json()
    assert "3 posts published" in rep["summary"] and "practice" in rep["summary"]
    assert rep["data"]["model"]["active"] is False
    assert client.get("/api/reports").json()[0]["id"] == rep["id"]
    assert client.get(f"/api/reports/{rep['id']}").json()["data"]["overview"]["totals"]["views"] == 3000
    # weekly dispatch: already has a fresh report
    assert report.dispatch_reports() == 0
    with session_scope() as s:
        s.query(Report).delete()
    assert report.dispatch_reports() == 1
    drain(Worker("w"), limit=3)
    with session_scope() as s:
        assert s.scalar(select(Report.id)) is not None
        assert "learned_model" in s.query(Workspace).one().settings


def test_reclip(client):
    client.get("/api/workspace")  # creates the workspace
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="ep.mp4", duration_s=60, status=VideoStatus.ready, stage=Stage.package)
        s.add(v)
        s.flush()
        vid = v.id
    assert client.post(f"/api/videos/{vid}/reclip").status_code == 409  # no transcript
    with session_scope() as s:
        s.add(Asset(video_id=vid, kind="transcript", path="x/transcript.json", size_bytes=1))
    r = client.post(f"/api/videos/{vid}/reclip")
    assert r.status_code == 200
    with session_scope() as s:
        v = s.get(Video, vid)
        assert v.status == VideoStatus.queued and v.stage == Stage.moments
        assert s.scalar(select(Job).where(Job.video_id == vid)).payload == {"stage": "moments"}
    assert client.post(f"/api/videos/{vid}/reclip").status_code == 409  # already queued
    assert client.get("/api/posts/00000000-0000-0000-0000-000000000000/metrics").status_code == 404


def test_account_scoped_endpoints_reject_other_ids(client):
    assert client.get("/api/analytics/overview", params={"account_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert client.get("/api/accounts/00000000-0000-0000-0000-000000000000/metrics").status_code == 404
