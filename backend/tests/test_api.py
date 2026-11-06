from datetime import datetime, timezone

from clipstar.db import session_scope
from clipstar.models import Clip, ClipStatus, Video, Workspace


def _acc(client, handle, platform="instagram", **kw):
    r = client.post("/api/accounts", json={"platform": platform, "handle": handle, "group_name": "Finance EN", "timezone": "America/New_York", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _clip(client, status=ClipStatus.approved):
    client.get("/api/workspace")  # creates the workspace
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="ep.mp4")
        s.add(v)
        s.flush()
        c = Clip(video_id=v.id, title="Rent trap", start_s=10, end_s=50, score=90, status=status, copy={"instagram": "IG caption"})
        s.add(c)
        s.flush()
        return str(c.id)


def test_health(client):
    h = client.get("/api/health").json()
    assert h["database"] and h["ffmpeg"] and h["storage_writable"]


def test_account_validation_and_duplicates(client):
    _acc(client, "@maya")
    assert client.post("/api/accounts", json={"platform": "instagram", "handle": "@maya"}).status_code == 409
    assert client.post("/api/accounts", json={"platform": "instagram", "handle": "@x", "timezone": "Mars/Base"}).status_code == 422
    assert client.post("/api/accounts", json={"platform": "myspace", "handle": "@x"}).status_code == 422
    assert client.post("/api/accounts", json={"platform": "tiktok", "handle": "@x", "posting_start": "25:00"}).status_code == 422
    a = _acc(client, "@maya", platform="tiktok")
    r = client.patch(f"/api/accounts/{a['id']}", json={"status": "paused", "daily_cap": 3})
    assert r.json()["status"] == "paused" and r.json()["daily_cap"] == 3
    assert len(client.get("/api/accounts", params={"platform": "tiktok"}).json()) == 1


def test_batch_lifecycle_and_post_filters(client):
    clip = _clip(client)
    a1, a2 = _acc(client, "@a"), _acc(client, "@b", platform="tiktok")
    body = {"name": "Ep batch", "clip_ids": [clip], "account_ids": [a1["id"], a2["id"]], "start_at": datetime(2030, 1, 1, 18, tzinfo=timezone.utc).isoformat(), "spacing_minutes": 45}
    b = client.post("/api/batches", json=body).json()
    assert b["status"] == "awaiting" and b["posts"] == 2 and b["accounts"] == 2

    posts = client.get("/api/posts", params={"batch_id": b["id"]}).json()
    assert {p["status"] for p in posts} == {"held"}
    assert posts[0]["caption"] in ("IG caption", "Rent trap")

    assert client.post(f"/api/batches/{b['id']}/disable").status_code == 409  # can't disable before approval
    assert client.post(f"/api/batches/{b['id']}/approve").json()["status"] == "running"
    assert {p["status"] for p in client.get("/api/posts", params={"batch_id": b["id"]}).json()} == {"scheduled"}
    assert client.post(f"/api/batches/{b['id']}/disable").json()["status"] == "disabled"
    assert {p["status"] for p in client.get("/api/posts", params={"batch_id": b["id"]}).json()} == {"held"}
    assert client.post(f"/api/batches/{b['id']}/enable").json()["status"] == "running"
    assert len(client.get("/api/posts", params={"platform": "tiktok"}).json()) == 1
    assert len(client.get("/api/posts", params={"account_id": a1["id"]}).json()) == 1
    assert client.post(f"/api/batches/{b['id']}/cancel").json()["status"] == "cancelled"
    assert {p["status"] for p in client.get("/api/posts", params={"batch_id": b["id"]}).json()} == {"cancelled"}


def test_batch_rejects_unapproved_clips_and_naive_times(client):
    clip = _clip(client, ClipStatus.pending)
    a = _acc(client, "@a")
    body = {"name": "x", "clip_ids": [clip], "account_ids": [a["id"]], "start_at": "2030-01-01T18:00:00Z"}
    assert client.post("/api/batches", json=body).status_code == 422
    client.patch(f"/api/clips/{clip}", json={"status": "approved"})
    body["start_at"] = "2030-01-01T18:00:00"
    assert client.post("/api/batches", json=body).status_code == 422


def test_clip_update_merges_copy(client):
    clip = _clip(client)
    r = client.patch(f"/api/clips/{clip}", json={"copy": {"tiktok": "tt"}, "hook": "THE RENT TRAP"})
    assert r.json()["copy"] == {"instagram": "IG caption", "tiktok": "tt"} and r.json()["hook"] == "THE RENT TRAP"


def test_engines_selection(client):
    engines = client.get("/api/engines").json()
    assert {e["id"] for e in engines} >= {"faster-whisper", "captions-file"}
    assert client.put("/api/engines/understand", json={"engine_id": "nope"}).status_code == 422
    r = client.put("/api/engines/understand", json={"engine_id": "captions-file"}).json()
    assert next(e for e in r if e["id"] == "captions-file")["selected"]


def test_api_token(client, monkeypatch):
    from clipstar.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "s3cret")
    assert client.get("/api/videos").status_code == 401
    assert client.get("/api/videos", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_unknown_ids_are_404(client):
    import uuid

    for path in ("/api/videos/", "/api/jobs/"):
        assert client.get(path + str(uuid.uuid4())).status_code == 404
    assert client.post(f"/api/batches/{uuid.uuid4()}/approve").status_code == 404
