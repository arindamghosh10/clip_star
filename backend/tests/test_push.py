import base64
import json

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select

from clipstar import push
from clipstar.db import session_scope
from clipstar.models import Account, AccountStatus, PushSubscription, Video, VideoStatus, Workspace
from clipstar.pipeline import register_all
from clipstar.worker import Worker

from .conftest import drain

H = {"X-ClipStar": "1"}
EP = "https://fcm.googleapis.com/fcm/send/abc123"


class Device:
    """A browser: its own key pair and auth secret, decrypting what the push service hands it."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.got = []
        self.code = 201

    def keys(self):
        pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {"p256dh": push.b64url(pub), "auth": push.b64url(self.auth)}

    def __call__(self, req: httpx.Request):
        assert req.headers["Content-Encoding"] == "aes128gcm" and int(req.headers["TTL"]) > 0
        msg = http_ece.decrypt(req.content, private_key=self.key, auth_secret=self.auth, version="aes128gcm")
        self.got.append((json.loads(msg), req.headers["Authorization"], req.headers["Urgency"]))
        return httpx.Response(self.code)


@pytest.fixture
def device(client):
    register_all()
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    d = Device()
    push.set_transport(httpx.MockTransport(d))
    yield d
    push.set_transport(None)


def test_vapid_signature_verifies(device):
    hdr = push.vapid_header(EP)
    t = hdr.split("t=")[1].split(",")[0]
    k = hdr.split("k=")[1]
    head, claims, sig = t.split(".")
    pad = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    assert json.loads(pad(claims))["aud"] == "https://fcm.googleapis.com"
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pad(k))
    raw = pad(sig)
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    assert k == push.public_key()


def test_subscribe_test_and_endpoint_safety(client, device):
    assert client.get("/api/push/key").json()["public_key"] == push.public_key()
    assert client.post("/api/push/test", headers=H).status_code == 409  # nothing subscribed
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example.com/x", "https://127.0.0.1/x", "https://fcm.googleapis.com.evil.com/x"):
        assert client.post("/api/push/subscriptions", json={"endpoint": bad, "keys": device.keys()}, headers=H).status_code == 422, bad
    r = client.post("/api/push/subscriptions", json={"endpoint": EP, "keys": device.keys()}, headers=H)
    assert r.status_code == 201 and r.json()["devices"] == 1
    assert client.post("/api/push/subscriptions", json={"endpoint": EP, "keys": device.keys()}, headers=H).json()["devices"] == 1  # same device once
    assert client.post("/api/push/test", headers=H).json()["sent"] == 1
    assert device.got[0][0]["title"] == "clip_star test"


def test_notifications_are_pushed_by_preference(client, device):
    client.post("/api/push/subscriptions", json={"endpoint": EP, "keys": device.keys()}, headers=H)
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep 3", source_filename="a.mp4")
        a = Account(workspace_id=ws.id, platform="x", handle="@m", connection="simulated")
        s.add_all([v, a])
        s.flush()
        v.status = VideoStatus.failed  # in the default push list
        a.status = AccountStatus.reconnect
    assert push.dispatch() == 2
    drain(Worker("w"), limit=5)
    titles = sorted(m["title"] for m, _, _ in device.got)
    assert titles == ["Reconnect @m (x)", "“Ep 3” stopped"]
    failed = next(m for m, _, u in device.got if "stopped" in m["title"])
    assert failed["url"].startswith(f"/videos/") and f"ws={ws.id}" in failed["url"]
    assert any(u == "high" for _, _, u in device.got)  # errors are urgent
    assert push.dispatch() == 0  # pushed once only
    # turning one kind off
    client.patch("/api/push/prefs", json={"kinds": ["lead"]}, headers=H)
    with session_scope() as s:
        v = Video(workspace_id=ws.id, title="Ep 4", source_filename="a.mp4")
        s.add(v)
        s.flush()
        v.status = VideoStatus.failed
    push.dispatch()
    drain(Worker("w"), limit=3)
    assert len(device.got) == 2


def test_gone_devices_are_removed(client, device):
    client.post("/api/push/subscriptions", json={"endpoint": EP, "keys": device.keys()}, headers=H)
    device.code = 410
    assert client.post("/api/push/test", headers=H).json()["removed"] == 1
    with session_scope() as s:
        assert s.scalar(select(PushSubscription.id)) is None
    assert client.get("/api/push/status").json()["devices"] == 0
