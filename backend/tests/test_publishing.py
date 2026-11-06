import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import update

from clipstar.db import session_scope
from clipstar.jobs import queue
from clipstar.models import Account, AccountStatus, Batch, Clip, ClipStatus, Job, Post, PostStatus, Video, Workspace
from clipstar.pipeline import register_all
from clipstar.platforms import simulated
from clipstar.platforms.base import Identity, PublishResult, Tokens
from clipstar.platforms.registry import PROVIDERS
from clipstar.publishing import service as svc
from clipstar.secrets import decrypt_json
from clipstar.storage import get_storage
from clipstar.worker import Worker

from .conftest import drain

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()
    client.patch("/api/workspace", json={"settings": {"quiet_hours": False, "spacing_minutes": 0}})
    simulated._failed_once.clear()
    simulated._ambiguous_created.clear()


def make_clip(client, score=90):
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="ep.mp4", duration_s=100)
        s.add(v)
        s.flush()
        st = get_storage()
        rel = f"videos/{v.id}/clips/x/A.mp4"
        st.abs(rel).parent.mkdir(parents=True, exist_ok=True)
        st.abs(rel).write_bytes(b"\x00" * 1000)
        c = Clip(video_id=v.id, title="Rent trap", start_s=10, end_s=40, score=score, status=ClipStatus.approved,
                 variants=[{"id": "A", "caption_style": "bold-pop", "hook": "RENT"}],
                 copy={"instagram": {"title": "", "caption": "Check your lease", "hashtags": ["rent"]}, "x": {"title": "", "caption": "Rent trap", "hashtags": []}},
                 meta={"renders": {"A": {"path": rel, "key": "k"}}})
        s.add(c)
        s.flush()
        return str(c.id), str(v.id)


def make_account(client, handle="@maya", platform="instagram", simulate=None, **kw):
    a = client.post("/api/accounts", json={"platform": platform, "handle": handle, "group_name": "Finance EN", **kw}).json()
    if simulate:
        r = client.patch(f"/api/accounts/{a['id']}", json={"options": {"simulate": simulate}})
        assert r.status_code == 200, r.text
    return a


def batch(client, clip_id, account_ids, approve=True):
    r = client.post("/api/batches", json={"name": "B", "clip_ids": [clip_id], "account_ids": account_ids, "start_at": (NOW() - timedelta(minutes=1)).isoformat()})
    assert r.status_code == 201, r.text
    b = r.json()
    if approve:
        assert client.post(f"/api/batches/{b['id']}/approve").json()["status"] == "running"
    return b


def posts(client, batch_id):
    return client.get("/api/posts", params={"batch_id": batch_id}).json()


def run(n=10):
    svc.dispatch()
    return drain(Worker("w"), limit=n)


def due_now(post_id):
    with session_scope() as s:
        s.execute(update(Post).where(Post.id == post_id).values(scheduled_at=NOW() - timedelta(seconds=1)))
        s.execute(update(Job).where(Job.status == "queued").values(run_after=NOW() - timedelta(seconds=1)))


def test_happy_path_publishes_once_and_finishes_batch(client):
    clip, _ = make_clip(client)
    a = make_account(client)
    b = batch(client, clip, [a["id"]])
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "published" and p["remote_id"].startswith("sim-") and p["attempts"] == 1, (p, client.get("/api/jobs").json()[:3])
    assert client.get("/api/batches").json()[0]["status"] == "finished"
    assert run() == 0  # nothing left; never sent twice


def test_disabling_after_dispatch_stops_the_post(client):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client)["id"]])
    svc.dispatch()  # job queued
    client.post(f"/api/batches/{b['id']}/disable")
    drain(Worker("w"))
    assert posts(client, b["id"])[0]["status"] == "held"


def test_temporary_failure_retries_with_backoff(client):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client, simulate="fail_once")["id"]])
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "scheduled" and p["attempts"] == 1 and "temporary" in p["last_error"]
    assert datetime.fromisoformat(p["scheduled_at"]) > NOW()
    due_now(p["id"])
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "published" and p["attempts"] == 2


def test_uncertain_result_is_verified_not_reposted(client, monkeypatch):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client, simulate="timeout")["id"]])
    calls = {"n": 0}
    orig = simulated.Simulated.publish

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(simulated.Simulated, "publish", counting)
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "unknown"
    due_now(p["id"])
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "published" and "Confirmed" in p["last_error"] and calls["n"] == 1


def test_unconfirmed_post_gives_up_without_reposting(client, monkeypatch):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client, simulate="timeout")["id"]])
    run()
    monkeypatch.setattr(simulated.Simulated, "find", lambda *a, **k: None)
    pid = posts(client, b["id"])[0]["id"]
    for _ in range(3):
        due_now(pid)
        run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "failed" and "Couldn't confirm" in p["last_error"]
    # the user checks the platform and decides
    assert client.post(f"/api/posts/{pid}/mark-published").json()["status"] == "published"


def test_expired_login_marks_account_for_reconnect(client):
    clip, _ = make_clip(client)
    a = make_account(client, simulate="expired")
    b = batch(client, clip, [a["id"]])
    run()
    assert posts(client, b["id"])[0]["status"] == "failed"
    acc = next(x for x in client.get("/api/accounts").json() if x["id"] == a["id"])
    assert acc["status"] == "reconnect" and "expired" in acc["last_error"]


def test_paused_account_waits_and_cap_moves_to_tomorrow(client):
    clip, _ = make_clip(client)
    a = make_account(client, daily_cap=1)
    b = batch(client, clip, [a["id"]])
    client.patch(f"/api/accounts/{a['id']}", json={"status": "paused"})
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "scheduled" and "paused" in p["last_error"]
    # unpause, but the daily limit is already used by another published post today
    client.patch(f"/api/accounts/{a['id']}", json={"status": "connected"})
    clip2, _ = make_clip(client)
    with session_scope() as s:
        other = Post(batch_id=p["batch_id"], account_id=a["id"], clip_id=clip2, variant="A", caption="x", scheduled_at=NOW(), status=PostStatus.published, published_at=NOW())
        s.add(other)
    due_now(p["id"])
    run()
    p = next(x for x in posts(client, b["id"]) if x["id"] == p["id"])
    assert p["status"] == "scheduled" and "Daily limit" in p["last_error"] and datetime.fromisoformat(p["scheduled_at"]) > NOW()


def test_worker_crash_mid_publish_is_verified(client):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client)["id"]])
    pid = posts(client, b["id"])[0]["id"]
    with session_scope() as s:
        s.execute(update(Post).where(Post.id == pid).values(status=PostStatus.publishing, started_at=NOW() - timedelta(hours=1)))
    svc.dispatch()
    assert posts(client, b["id"])[0]["status"] == "unknown"


def test_post_retry_and_cancel(client):
    clip, _ = make_clip(client)
    b = batch(client, clip, [make_account(client, simulate="fail")["id"], make_account(client, "@two")["id"]])
    run()
    ps = {p["status"] for p in posts(client, b["id"])}
    assert ps == {"failed", "published"}
    failed = next(p for p in posts(client, b["id"]) if p["status"] == "failed")
    assert client.post(f"/api/posts/{failed['id']}/retry").json()["status"] == "scheduled"
    assert client.post(f"/api/posts/{failed['id']}/cancel").json()["status"] == "cancelled"
    assert client.get("/api/batches").json()[0]["status"] == "finished"


def test_late_approval_shifts_the_plan(client):
    clip, _ = make_clip(client)
    r = client.post("/api/batches", json={"name": "B", "clip_ids": [clip], "account_ids": [make_account(client)["id"]], "start_at": (NOW() - timedelta(days=2)).isoformat()})
    b = r.json()
    client.post(f"/api/batches/{b['id']}/approve")
    assert datetime.fromisoformat(posts(client, b["id"])[0]["scheduled_at"]) > NOW() - timedelta(minutes=1)


def test_rules_create_one_batch_per_video(client):
    clip, vid = make_clip(client, score=80)
    make_account(client)
    client.post("/api/rules", json={"name": "Top clips", "config": {"min_score": 70, "groups": ["Finance EN"], "start_delay_minutes": 0}})
    with session_scope() as s:
        svc.queue_rules(s, vid)
    drain(Worker("w"))
    with session_scope() as s:
        svc.queue_rules(s, vid)
    drain(Worker("w"))
    bs = client.get("/api/batches").json()
    assert len(bs) == 1 and bs[0]["status"] == "awaiting" and bs[0]["origin"].startswith("rule:")


# ---------- connecting real accounts (platform calls replaced) ----------


class FakeX:
    platform = "x"
    label = "X"
    scopes = ["tweet.write"]
    docs_url = ""
    client_id_label = "Client ID"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return f"https://x.example/authorize?state={state}&client_id={app.client_id}&redirect_uri={redirect_uri}"

    def exchange(self, app, code, redirect_uri, verifier):
        assert code == "good" and app.client_secret == "s3cret" and verifier
        return Tokens("ACCESS-123", "REFRESH-456", time.time() + 3600)

    def identities(self, app, tokens):
        return [Identity("42", "@maya", tokens, {"username": "maya"})]

    def refresh(self, app, tokens):
        return Tokens("ACCESS-NEW", tokens.refresh_token, time.time() + 7200)

    def publish(self, app, tokens, remote_id, req):
        assert tokens.access_token == "ACCESS-NEW" and remote_id == "42" and req.caption.startswith("Rent trap")
        return PublishResult("tw-1", "https://x.com/maya/status/tw-1")

    def find(self, *a, **k):
        return None


def test_oauth_connect_refresh_and_publish(client, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "x", FakeX())
    assert client.post("/api/connect/x/start", json={}).status_code == 409  # no app keys yet
    assert client.put("/api/platforms/x/app", json={"client_id": "cid", "client_secret": "s3cret"}).status_code == 200
    plats = {p["platform"]: p for p in client.get("/api/platforms").json()}
    assert plats["x"]["configured"] and "client_secret" not in plats["x"] and plats["x"]["redirect_uri"].endswith("/api/connect/x/callback")

    url = client.post("/api/connect/x/start", json={"group_name": "Finance EN"}).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    r = client.get("/api/connect/x/callback", params={"state": state, "code": "good"}, follow_redirects=False)
    assert r.status_code == 302 and "connected=%40maya" in r.headers["location"]
    r2 = client.get("/api/connect/x/callback", params={"state": state, "code": "good"}, follow_redirects=False)
    assert "error=" in r2.headers["location"]  # a state works once
    assert "error=" in client.get("/api/connect/x/callback", params={"state": "forged", "code": "good"}, follow_redirects=False).headers["location"]

    acc = next(a for a in client.get("/api/accounts").json() if a["platform"] == "x")
    assert acc["connection"] == "oauth" and acc["remote_id"] == "42" and acc["group_name"] == "Finance EN" and "token_enc" not in acc
    with session_scope() as s:
        row = s.get(Account, acc["id"])
        assert "ACCESS-123" not in row.token_enc and decrypt_json(row.token_enc)["access_token"] == "ACCESS-123"
        # make it expire soon -> the publisher refreshes first
        row.token_enc = svc.encrypt({"access_token": "OLD", "refresh_token": "REFRESH-456", "expires_at": time.time() + 30, "extra": {}})

    clip, _ = make_clip(client)
    b = batch(client, clip, [acc["id"]])
    run()
    p = posts(client, b["id"])[0]
    assert p["status"] == "published" and p["remote_url"] == "https://x.com/maya/status/tw-1"
    with session_scope() as s:
        assert decrypt_json(s.get(Account, acc["id"]).token_enc)["access_token"] == "ACCESS-NEW"


def test_public_media_links_are_signed_and_expire(client):
    clip, _ = make_clip(client)
    with session_scope() as s:
        rel = s.get(Clip, clip).meta["renders"]["A"]["path"]
    url = svc.public_media_url(rel)
    assert url.startswith("https://clips.example.com/api/public/media/")
    path = urlparse(url).path
    assert client.get(path).status_code == 200
    assert client.get(path[:-4] + "AAAA").status_code == 404
    expired = svc.encrypt({"p": rel, "exp": time.time() - 1})
    assert client.get(f"/api/public/media/{expired}").status_code == 404
