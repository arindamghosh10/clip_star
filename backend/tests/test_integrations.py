import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipstar import webhooks
from clipstar.api.main import app
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.models import Clip, ClipStatus, Event, Job, Notification, Video, VideoStatus, Webhook, WebhookDelivery, Workspace
from clipstar.pipeline import register_all
from clipstar.worker import Worker

from .conftest import drain

H = {"X-ClipStar": "1"}
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": PW, "workspace_name": "W"}, headers=H)


def ws_id():
    with session_scope() as s:
        return s.query(Workspace).one().id


def bearer(k):
    return {"Authorization": f"Bearer {k}"}


# ---------- API keys ----------


def test_api_keys_act_as_their_owner_with_capped_role(client):
    r = client.post("/api/keys", json={"name": "zapier", "role": "editor"}, headers=H)
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("cs_") and r.json()["prefix"] == key[:10]
    assert "key" not in client.get("/api/keys").json()[0]  # shown once only

    bot = TestClient(app)
    assert bot.get("/api/videos", headers=bearer(key)).status_code == 200
    assert bot.post("/api/accounts", json={"platform": "x", "handle": "@k"}, headers=bearer(key)).status_code == 201  # editor, no CSRF header needed
    assert bot.put("/api/admin/budget", json={"monthly_budget_usd": 1}, headers=bearer(key)).status_code == 403  # owner-only, key is editor
    assert bot.post("/api/keys", json={"name": "x"}, headers=bearer(key)).status_code == 403  # keys can't mint keys
    assert bot.get("/api/videos", headers=bearer("cs_nope")).status_code == 401

    kid = client.get("/api/keys").json()[0]["id"]
    assert client.delete(f"/api/keys/{kid}", headers=H).status_code == 204
    assert bot.get("/api/videos", headers=bearer(key)).status_code == 401


def test_key_can_not_exceed_person_and_follows_demotion(client):
    tok = client.post("/api/users", json={"email": "v@example.com", "role": "editor"}, headers=H).json()["invite_url"].split("token=")[1]
    ed = TestClient(app)
    ed.post("/api/auth/invite/accept", json={"token": tok, "name": "Ed", "password": PW}, headers=H)
    assert ed.post("/api/keys", json={"name": "too much", "role": "owner"}, headers=H).status_code == 403
    key = ed.post("/api/keys", json={"name": "ok", "role": "editor"}, headers=H).json()["key"]
    assert TestClient(app).post("/api/accounts", json={"platform": "x", "handle": "@e"}, headers=bearer(key)).status_code == 201
    uid = next(u["id"] for u in client.get("/api/users").json() if u["email"] == "v@example.com")
    client.patch(f"/api/users/{uid}", json={"role": "viewer"}, headers=H)
    assert TestClient(app).post("/api/accounts", json={"platform": "x", "handle": "@f"}, headers=bearer(key)).status_code == 403  # now viewer
    client.patch(f"/api/users/{uid}", json={"disabled": True}, headers=H)
    assert TestClient(app).get("/api/videos", headers=bearer(key)).status_code == 401
    assert len(client.get("/api/keys").json()) == 1  # owner sees everyone's keys
    assert ed.get("/api/keys").status_code == 401


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_key_rate_per_minute", 3)
    key = client.post("/api/keys", json={"name": "k"}, headers=H).json()["key"]
    codes = [TestClient(app).get("/api/videos", headers=bearer(key)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_docs_are_published(client):
    spec = TestClient(app).get("/api/openapi.json").json()
    assert "/api/events" in spec["paths"] and "/api/clips/{clip_id}" in spec["paths"]
    assert TestClient(app).get("/api/docs").status_code == 200


# ---------- events ----------


def make_video_ready():
    with session_scope() as s:
        v = Video(workspace_id=ws_id(), title="Ep 9", source_filename="a.mp4")
        s.add(v)
        s.flush()
        s.add(Clip(video_id=v.id, title="C", start_s=0, end_s=20, score=70, status=ClipStatus.pending))
        vid = v.id
    with session_scope() as s:
        s.get(Video, vid).status = VideoStatus.ready
    return vid


def test_event_feed_in_order_with_cursor(client):
    vid = make_video_ready()
    with session_scope() as s:
        c = s.scalar(select(Clip).where(Clip.video_id == vid))
        c.status = ClipStatus.approved
        cid = c.id
    r = client.get("/api/events").json()
    assert [e["type"] for e in r["events"]] == ["video.ready", "clip.approved"]
    assert r["events"][0]["data"]["clips"] == 1 and r["events"][1]["data"]["clip_id"] == str(cid)
    after = r["events"][0]["id"]
    assert [e["type"] for e in client.get("/api/events", params={"after": after}).json()["events"]] == ["clip.approved"]
    assert client.get("/api/events", params={"types": "video.ready"}).json()["events"][0]["type"] == "video.ready"
    assert client.get("/api/events", params={"after": r["next_after"]}).json()["events"] == []


def test_publishing_flow_emits_events(client):
    from .test_publishing import make_clip

    acc = client.post("/api/accounts", json={"platform": "instagram", "handle": "@maya"}, headers=H).json()
    cid, _ = make_clip(client)
    from datetime import datetime, timedelta, timezone

    start = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    b = client.post("/api/batches", json={"name": "B", "clip_ids": [cid], "account_ids": [acc["id"]], "groups": [], "start_at": start, "variations": "off"}, headers=H)
    assert b.status_code == 201, b.text
    client.post(f"/api/batches/{b.json()['id']}/approve", headers=H)
    types = [e["type"] for e in client.get("/api/events").json()["events"]]
    assert types[-2:] == ["batch.awaiting_approval", "batch.approved"]


# ---------- webhooks ----------


class Receiver:
    def __init__(self, codes=(200,)):
        self.got = []
        self.codes = list(codes)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.got.append((dict(self.headers), body))
                code = outer.codes.pop(0) if len(outer.codes) > 1 else outer.codes[0]
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/hook"

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)
    monkeypatch.setattr(get_settings(), "job_backoff_base_seconds", 0.0)
    r = Receiver()
    yield r
    r.close()


def test_url_safety(client, monkeypatch):
    for bad in ("ftp://x.com", "http://localhost:9000/x", "http://127.0.0.1/x", "http://10.1.2.3/x", "http://user:pw@example.com/x", "http://box.internal/x"):
        assert client.post("/api/webhooks", json={"url": bad}, headers=H).status_code == 422, bad
    # a public-looking name that resolves to an internal address is blocked at send time
    r = client.post("/api/webhooks", json={"url": "https://hooks.example.com/x", "events": ["video.ready"]}, headers=H)
    assert r.status_code == 201
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))])
    make_video_ready()
    assert webhooks.dispatch() == 1
    drain(Worker("w"), limit=3)
    with session_scope() as s:
        d = s.scalar(select(WebhookDelivery))
        assert d.status == "failed" and "internal address" in (s.scalar(select(Job.last_error).where(Job.kind == webhooks.KIND)) or "")


def test_signed_delivery_only_for_subscribed_events(client, receiver):
    r = client.post("/api/webhooks", json={"url": receiver.url, "events": ["video.ready"], "description": "n8n"}, headers=H).json()
    secret = r["secret"]
    assert secret.startswith("whsec_") and "secret" not in client.get("/api/webhooks").json()[0]
    vid = make_video_ready()
    with session_scope() as s:
        s.scalar(select(Clip).where(Clip.video_id == vid)).status = ClipStatus.approved  # not subscribed
    assert webhooks.dispatch() == 1
    assert webhooks.dispatch() == 0  # each event fanned out once
    drain(Worker("w"), limit=3)
    assert len(receiver.got) == 1
    headers, body = receiver.got[0]
    assert headers["X-ClipStar-Event"] == "video.ready"
    assert webhooks.verify(secret, body, headers["X-ClipStar-Signature"])
    assert not webhooks.verify("whsec_wrong", body, headers["X-ClipStar-Signature"])
    msg = json.loads(body)
    assert msg["type"] == "video.ready" and msg["data"]["title"] == "Ep 9"
    d = client.get(f"/api/webhooks/{r['id']}/deliveries").json()[0]
    assert d["status"] == "sent" and d["response_code"] == 200 and d["attempts"] == 1


def test_retry_then_success_and_redeliver_and_test_ping(client, receiver):
    receiver.codes = [503, 200]
    r = client.post("/api/webhooks", json={"url": receiver.url}, headers=H).json()
    make_video_ready()
    webhooks.dispatch()
    drain(Worker("w"), limit=5)
    assert len(receiver.got) == 2  # 503, then retried
    d = client.get(f"/api/webhooks/{r['id']}/deliveries").json()[0]
    assert d["status"] == "sent" and d["attempts"] == 2
    assert receiver.got[0][0]["X-ClipStar-Delivery"] == receiver.got[1][0]["X-ClipStar-Delivery"]  # same id on retry
    assert client.post(f"/api/webhooks/{r['id']}/deliveries/{d['id']}/retry", headers=H).status_code == 202
    assert client.post(f"/api/webhooks/{r['id']}/test", headers=H).status_code == 202
    drain(Worker("w"), limit=5)
    assert [json.loads(b)["type"] for _, b in receiver.got[2:]] == ["video.ready", "ping"]


def test_permanent_refusal_and_auto_disable(client, receiver, monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_disable_after_failures", 2)
    receiver.codes = [410]
    r = client.post("/api/webhooks", json={"url": receiver.url}, headers=H).json()
    for _ in range(2):
        make_video_ready()
    webhooks.dispatch()
    drain(Worker("w"), limit=6)
    assert len(receiver.got) == 2  # 4xx: no retries
    h = client.get("/api/webhooks").json()[0]
    assert h["enabled"] is False and "2 failed deliveries" in h["disabled_reason"]
    with session_scope() as s:
        assert s.scalar(select(Notification.title).where(Notification.kind == "webhook")) == "A webhook was switched off"
    make_video_ready()
    assert webhooks.dispatch() == 0  # disabled hooks get nothing
    client.patch(f"/api/webhooks/{r['id']}", json={"enabled": True}, headers=H)
    assert client.get("/api/webhooks").json()[0]["consecutive_failures"] == 0


def test_webhooks_owner_only_and_validation(client):
    assert client.post("/api/webhooks", json={"url": "https://example.com/h", "events": ["nope"]}, headers=H).status_code == 422
    tok = client.post("/api/users", json={"email": "e@example.com", "role": "editor"}, headers=H).json()["invite_url"].split("token=")[1]
    ed = TestClient(app)
    ed.post("/api/auth/invite/accept", json={"token": tok, "name": "E", "password": PW}, headers=H)
    assert ed.post("/api/webhooks", json={"url": "https://example.com/h"}, headers=H).status_code == 403
    assert ed.get("/api/events").status_code == 200


def test_signature_check_rejects_old_timestamps():
    body = b"{}"
    old = webhooks.sign("whsec_x", body, t=1_000_000)
    assert not webhooks.verify("whsec_x", body, old)
    assert webhooks.verify("whsec_x", body, webhooks.sign("whsec_x", body))
