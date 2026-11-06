import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import update

from clipstar.db import session_scope
from clipstar.engage import service as eng
from clipstar.engage.engines import ClaudeEngageEngine, CommentIn
from clipstar.engage.rules import EngageSettings, classify
from clipstar.engines.llm import EngineDeclined
from clipstar.jobs.queue import utcnow
from clipstar.models import Account, Batch, BatchStatus, Clip, ClipStatus, Comment, Job, Post, PostStatus, Video, Workspace
from clipstar.pipeline import register_all
from clipstar.platforms import util
from clipstar.platforms.base import Ambiguous, App, AuthExpired, Tokens
from clipstar.platforms.http import set_transport
from clipstar.platforms.meta import Facebook, Instagram, Threads
from clipstar.platforms.registry import SIMULATED
from clipstar.platforms.x import X
from clipstar.platforms.youtube import YouTube
from clipstar.worker import Worker

from .conftest import drain


@pytest.mark.parametrize(
    "text,cat",
    [
        ("Does this work if you rent in the UK?", "question"),
        ("how do I find that clause", "question"),
        ("DM me to 10x your money 🚀", "spam"),
        ("great video check out my page www.spam.xyz", "spam"),
        ("Would love to collab, what are your rates?", "lead"),
        ("This is wrong and misleading", "critical"),
        ("Thank you so much ❤️", "praise"),
        ("ok", "other"),
    ],
)
def test_classify(text, cat):
    assert classify(text) == cat


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()


def published_post(client, handle="@maya", platform="instagram"):
    acc = client.post("/api/accounts", json={"platform": platform, "handle": handle}).json()
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="ep.mp4", duration_s=60)
        s.add(v)
        s.flush()
        c = Clip(video_id=v.id, title="Rent trap", start_s=0, end_s=30, score=80, status=ClipStatus.approved, meta={"words": [{"start": 0, "end": 1, "word": "Check"}, {"start": 1, "end": 2, "word": "your"}, {"start": 2, "end": 3, "word": "lease."}]})
        s.add(c)
        s.flush()
        b = Batch(workspace_id=ws.id, name="B", status=BatchStatus.running)
        s.add(b)
        s.flush()
        p = Post(batch_id=b.id, account_id=acc["id"], clip_id=c.id, caption="x", scheduled_at=utcnow(), status=PostStatus.published, published_at=utcnow(), remote_id=f"sim-{handle}")
        s.add(p)
    return acc


def sync(ws_id=None):
    with session_scope() as s:
        ws = s.query(Workspace).one()
    eng.dispatch_sync(force_workspace=ws.id)
    drain(Worker("w"), limit=30)


def comments(client, state="all"):
    return {c["author"]: c for c in client.get("/api/comments", params={"state": state}).json()}


def test_sync_sorts_and_drafts_without_duplicates(client):
    published_post(client)
    sync()
    cs = comments(client)
    assert {c["category"] for c in cs.values()} == {"question", "praise", "lead", "spam", "critical"}
    assert cs["@jordan_saves"]["draft"] and cs["@smallbiz.hq"]["draft"].startswith("Thanks for reaching out")
    assert cs["@priya.k"]["draft"] == "" and cs["@crypto_gainz_99"]["draft"] == ""
    assert cs["@priya.k"]["clip_title"] == "Rent trap" and all(c["state"] == "open" for c in cs.values())
    sync()
    assert len(client.get("/api/comments", params={"state": "all"}).json()) == 5
    s = client.get("/api/comments/summary").json()
    assert s["open"]["question"] == 1 and s["accounts"][0]["supported"] and s["accounts"][0]["synced_at"]


def test_auto_reply_praise_and_auto_hide_spam_with_hourly_limit(client):
    client.patch("/api/workspace", json={"settings": {"auto_reply_categories": ["praise", "lead"], "auto_hide_spam": True, "replies_per_hour": 1}})
    published_post(client)
    sync()
    cs = comments(client)
    assert cs["@crypto_gainz_99"]["hidden"] is True
    sent = [c for c in cs.values() if c["reply_status"] == "sent"]
    waiting = [c for c in cs.values() if c["reply_status"] == "queued"]
    assert len(sent) == 1 and len(waiting) == 1 and "limit" in waiting[0]["error"]
    assert sent[0]["reply_auto"] and cs["@priya.k"]["reply_status"] == "none"  # questions never auto-sent


def test_manual_send_and_guards(client):
    published_post(client)
    sync()
    q = comments(client)["@priya.k"]
    assert client.post(f"/api/comments/{q['id']}/send", json={"text": "x" * 3000}).status_code == 422
    r = client.post(f"/api/comments/{q['id']}/send", json={"text": "Mostly yes! UK video coming next week."})
    assert r.status_code == 200 and r.json()["reply_status"] == "queued"
    assert client.post(f"/api/comments/{q['id']}/send", json={"text": "again"}).status_code == 409
    drain(Worker("w"))
    q = comments(client)["@priya.k"]
    assert q["reply_status"] == "sent" and q["state"] == "done"
    assert client.post(f"/api/comments/{q['id']}/send", json={"text": "again"}).status_code == 409


def test_uncertain_reply_is_never_resent_without_confirmation(client, monkeypatch):
    published_post(client)
    sync()
    q = comments(client)["@priya.k"]

    def boom(*a, **k):
        raise Ambiguous("timeout", user_message="No answer from the platform.")

    monkeypatch.setattr(type(SIMULATED), "reply", boom)
    client.post(f"/api/comments/{q['id']}/send", json={"text": "Yes!"})
    drain(Worker("w"))
    q = comments(client)["@priya.k"]
    assert q["reply_status"] == "unknown"
    assert client.post(f"/api/comments/{q['id']}/send", json={"text": "Yes!"}).status_code == 409
    assert client.post(f"/api/comments/{q['id']}/mark-sent").json()["reply_status"] == "sent"


def test_temporary_error_retries_and_expired_login_needs_reconnect(client, monkeypatch):
    from clipstar.errors import RetryableError

    acc = published_post(client)
    sync()
    cs = comments(client)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RetryableError("429", user_message="rate limited")
        return "r1"

    monkeypatch.setattr(type(SIMULATED), "reply", flaky)
    client.post(f"/api/comments/{cs['@priya.k']['id']}/send", json={"text": "Yes!"})
    drain(Worker("w"))
    assert comments(client)["@priya.k"]["reply_status"] == "queued"
    with session_scope() as s:
        s.execute(update(Job).where(Job.status == "queued").values(run_after=datetime.now(timezone.utc) - timedelta(seconds=1)))
    drain(Worker("w"))
    assert comments(client)["@priya.k"]["reply_status"] == "sent"

    def expired(*a, **k):
        raise AuthExpired("x", user_message="Login expired. Reconnect the account.")

    monkeypatch.setattr(type(SIMULATED), "reply", expired)
    client.post(f"/api/comments/{cs['@tom.h']['id']}/send", json={"text": "Fair point."})
    drain(Worker("w"))
    assert comments(client)["@tom.h"]["reply_status"] == "failed"
    assert next(a for a in client.get("/api/accounts").json() if a["id"] == acc["id"])["status"] == "reconnect"


def test_category_edit_skip_reopen_and_hide(client):
    published_post(client)
    sync()
    c = comments(client)["@tom.h"]
    r = client.patch(f"/api/comments/{c['id']}", json={"category": "question", "draft": "Good point, here's why..."}).json()
    assert r["category"] == "question" and r["category_by"] == "user" and r["draft_by"] == "user"
    assert client.post(f"/api/comments/{c['id']}/skip").json()["state"] == "done"
    assert client.post(f"/api/comments/{c['id']}/reopen").json()["state"] == "open"
    client.post(f"/api/comments/{c['id']}/hide")
    drain(Worker("w"))
    assert comments(client)["@tom.h"]["hidden"] is True


def test_platforms_without_comment_access_are_skipped(client):
    acc = client.post("/api/accounts", json={"platform": "tiktok", "handle": "@t"}).json()
    with session_scope() as s:
        s.execute(update(Account).where(Account.id == acc["id"]).values(connection="oauth"))
    summary = client.get("/api/comments/summary").json()
    tt = next(a for a in summary["accounts"] if a["id"] == acc["id"])
    assert tt["supported"] is False and "TikTok" in tt["note"]


# ---------- AI drafts are checked ----------


def _items():
    st = EngageSettings(banned_topics=["crypto"])
    mk = lambda i, t: CommentIn(id=i, author="a", text=t, platform="x", clip_title="Rent", clip_text="check your lease", max_chars=280)  # noqa: E731
    return st, [mk("1", "Does this work in the UK?"), mk("2", "buy my course"), mk("3", "love it"), mk("4", "is crypto better?"), mk("5", "hi")]


class Ctx:
    attempt = 1

    def progress(self, *a, **k):
        pass

    def check(self):
        pass


def test_ai_drafts_are_validated(monkeypatch):
    st, items = _items()
    e = ClaudeEngageEngine()
    monkeypatch.setattr(e, "check", lambda: type("H", (), {"ok": True, "message": ""})())
    answer = {
        "items": [
            {"id": "1", "category": "question", "reply": "Mostly, yes. " + "a" * 400},
            {"id": "2", "category": "spam", "reply": "thanks!"},
            {"id": "3", "category": "praise", "reply": "Thanks! More at https://evil.example"},
            {"id": "4", "category": "question", "reply": "Crypto is great"},
            {"id": "99", "category": "praise", "reply": "unknown id"},
        ]
    }
    monkeypatch.setattr(e, "call", lambda s, p: json.dumps(answer))
    out, notes = e.process(Ctx(), items, st)
    assert out["1"].by == "claude" and len(out["1"].draft) <= 280
    assert out["2"].draft == ""  # spam never gets a reply
    assert out["3"].by == "rules" and "http" not in out["3"].draft  # link replaced by template
    assert out["4"].by == "rules"  # banned topic
    assert out["5"].by == "rules"  # missing from answer -> rules


def test_ai_declined_falls_back(monkeypatch):
    st, items = _items()
    e = ClaudeEngageEngine()
    monkeypatch.setattr(e, "check", lambda: type("H", (), {"ok": True, "message": ""})())

    def no(s, p):
        raise EngineDeclined("the model declined this request")

    monkeypatch.setattr(e, "call", no)
    out, notes = e.process(Ctx(), items, st)
    assert all(o.by == "rules" for o in out.values()) and "declined" in notes[0]


# ---------- platform request sequences ----------

APP = App("cid", "secret")
TOK = Tokens("TOKEN", extra={"username": "maya"})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(util, "sleep", lambda s: None)
    log = []

    def install(routes):
        def handler(req):
            log.append(req)
            for m, frag, fn in routes:
                if req.method == m and frag in str(req.url):
                    return fn(req)
            return httpx.Response(404, json={"error": {"message": "no route"}})

        set_transport(httpx.MockTransport(handler))
        return log

    yield install
    set_transport(None)


def J(d, status=200):
    return lambda r: httpx.Response(status, json=d)


def test_youtube_comments(fake):
    log = fake(
        [
            ("GET", "/commentThreads", J({"items": [{"id": "t1", "snippet": {"topLevelComment": {"id": "c1", "snippet": {"authorDisplayName": "Priya", "textDisplay": "UK?", "publishedAt": "2026-11-06T10:00:00Z", "authorChannelId": {"value": "other"}}}}}, {"id": "t2", "snippet": {"topLevelComment": {"id": "c2", "snippet": {"authorDisplayName": "Me", "textDisplay": "pinned", "authorChannelId": {"value": "chan"}}}}}]})),
            ("POST", "/comments/setModerationStatus", J({}, 204)),
            ("POST", "/youtube/v3/comments", J({"id": "r1"})),
        ]
    )
    cs = YouTube().list_comments(APP, TOK, "chan", "vid")
    assert [(c.remote_id, c.is_own) for c in cs] == [("c1", False), ("c2", True)] and cs[0].created_at.year == 2026
    assert YouTube().reply(APP, TOK, "chan", "vid", "c1", "Yes!") == "r1"
    assert json.loads(log[-1].content)["snippet"] == {"parentId": "c1", "textOriginal": "Yes!"}
    YouTube().hide(APP, TOK, "chan", "c1")
    assert "moderationStatus=heldForReview" in str(log[-1].url)


def test_instagram_facebook_threads_x_comments(fake):
    log = fake(
        [
            ("GET", "/media1/comments", J({"data": [{"id": "ic1", "text": "love it", "username": "fan", "timestamp": "2026-11-06T10:00:00+0000"}, {"id": "ic2", "text": "thanks!", "username": "maya"}]})),
            ("POST", "/ic1/replies", J({"id": "ir1"})),
            ("POST", "/ic1", J({"success": True})),
            ("GET", "/vid1/comments", J({"data": [{"id": "fc1", "message": "great", "from": {"id": "u9", "name": "Dan"}, "created_time": "2026-11-06T10:00:00+0000"}]})),
            ("POST", "/fc1/comments", J({"id": "fr1"})),
            ("GET", "/th1/replies", J({"data": [{"id": "tc1", "text": "nice", "username": "z"}]})),
            ("POST", "/u1/threads_publish", J({"id": "tr1"})),
            ("POST", "/u1/threads", J({"id": "cont"})),
            ("GET", "/tweets/search/recent", J({"data": [{"id": "x1", "text": "UK?", "author_id": "7", "created_at": "2026-11-06T10:00:00Z"}], "includes": {"users": [{"id": "7", "username": "priya"}]}})),
            ("POST", "/2/tweets", J({"data": {"id": "xr1"}})),
            ("PUT", "/hidden", J({"data": {"hidden": True}})),
        ]
    )
    ig = Instagram().list_comments(APP, TOK, "ig", "media1")
    assert [(c.author, c.is_own) for c in ig] == [("fan", False), ("maya", True)]
    assert Instagram().reply(APP, TOK, "ig", "media1", "ic1", "Thanks!") == "ir1"
    Instagram().hide(APP, TOK, "ig", "ic1")
    assert b"hide=true" in log[-1].content
    fb = Facebook().list_comments(APP, TOK, "page", "vid1")
    assert fb[0].author == "Dan" and Facebook().reply(APP, TOK, "page", "vid1", "fc1", "Thanks") == "fr1"
    assert Threads().list_comments(APP, TOK, "u1", "th1")[0].remote_id == "tc1"
    assert Threads().reply(APP, TOK, "u1", "th1", "tc1", "hey") == "tr1"
    assert any(b"reply_to_id=tc1" in r.content for r in log)
    xs = X().list_comments(APP, TOK, "42", "tw1")
    assert xs[0].author == "@priya" and "conversation_id%3Atw1" in str([r.url for r in log if "search" in str(r.url)][0])
    assert X().reply(APP, TOK, "42", "tw1", "x1", "Yes") == "xr1"
    assert json.loads([r for r in log if str(r.url).endswith("/2/tweets")][-1].content)["reply"] == {"in_reply_to_tweet_id": "x1"}
    X().hide(APP, TOK, "42", "x1")
    assert json.loads(log[-1].content) == {"hidden": True}
