import json
import subprocess

import httpx
import pytest
from sqlalchemy import select

from clipstar import external_clippers as ec
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.models import Asset, Clip, Video, VideoStatus, Workspace
from clipstar.pipeline import register_all
from clipstar.storage import get_storage
from clipstar.worker import Worker

from .conftest import drain


@pytest.fixture
def clip_bytes(tmp_path_factory):
    p = tmp_path_factory.mktemp("ext") / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=540x960:rate=25:duration=3", "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", "-y", str(p)], check=True)
    return p.read_bytes()


@pytest.fixture
def video(client, monkeypatch):
    register_all()
    client.get("/api/workspace")
    monkeypatch.setattr(get_settings(), "public_media_url", "https://clips.example.com")
    monkeypatch.setattr(ec, "POLL_S", 0)
    st = get_storage()
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="a.mp4", status=VideoStatus.ready)
        s.add(v)
        s.flush()
        rel = st.rel(v.id, "master.mp4")
        st.abs(rel).parent.mkdir(parents=True, exist_ok=True)
        st.abs(rel).write_bytes(b"x")
        s.add(Asset(video_id=v.id, kind="master", path=rel, size_bytes=1))
        return str(v.id)


def test_vizard_clips_arrive_for_review(client, video, clip_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "vizard_api_key", "vz")
    states = iter([{"code": 1000}, {"code": 2000, "videos": [{"videoUrl": "https://cdn.vizard.test/c1.mp4", "title": "Rent trap", "viralScore": "8.6", "viralReason": "Strong hook"}]}])
    seen = []

    def h(req):
        seen.append(req)
        if req.url.path.endswith("/project/create"):
            return httpx.Response(200, json={"code": 2000, "projectId": 77})
        if "/project/query/77" in req.url.path:
            return httpx.Response(200, json=next(states))
        if req.url.host == "cdn.vizard.test":
            return httpx.Response(200, content=clip_bytes)
        return httpx.Response(404)

    ec.set_transport(httpx.MockTransport(h))
    try:
        assert client.post(f"/api/videos/{video}/external-clips", json={"vendor": "vizard"}).status_code == 202
        drain(Worker("w"), limit=3)
    finally:
        ec.set_transport(None)
    body = json.loads(seen[0].content)
    assert seen[0].headers["vizardai_api_key"] == "vz" and body["videoType"] == 1 and body["videoUrl"].startswith("https://clips.example.com/api/public/media/")
    with session_scope() as s:
        c = s.scalar(select(Clip).where(Clip.video_id == video))
        assert c.title == "Rent trap" and c.score == 86 and c.status.value == "pending" and c.meta["external"] == "vizard"
        assert c.copy and get_storage().exists(c.meta["renders"]["A"]["path"]) and abs(c.end_s - 3) < 0.3
        cid = str(c.id)
    # can't be re-cut or re-rendered, but text and approval work
    assert client.patch(f"/api/clips/{cid}", json={"start_s": 1, "end_s": 2}).status_code == 409
    assert client.post(f"/api/clips/{cid}/render").status_code == 409
    assert client.patch(f"/api/clips/{cid}", json={"status": "approved", "title": "Rent trap!"}).status_code == 200


def test_klap_flow(client, video, clip_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "klap_api_key", "kl")

    def h(req):
        p = req.url.path
        if p == "/v2/tasks/video-to-shorts":
            return httpx.Response(200, json={"id": "t1", "status": "processing"})
        if p == "/v2/tasks/t1":
            return httpx.Response(200, json={"id": "t1", "status": "ready", "output_id": "f1"})
        if p == "/v2/projects/f1":
            return httpx.Response(200, json=[{"id": "p1", "name": "Lease secrets", "virality_score": 72}])
        if p == "/v2/projects/f1/p1/exports" and req.method == "POST":
            return httpx.Response(200, json={"id": "e1", "status": "processing"})
        if p == "/v2/projects/f1/p1/exports/e1":
            return httpx.Response(200, json={"id": "e1", "status": "ready", "src_url": "https://cdn.klap.test/e1.mp4"})
        if req.url.host == "cdn.klap.test":
            return httpx.Response(200, content=clip_bytes)
        return httpx.Response(404)

    ec.set_transport(httpx.MockTransport(h))
    try:
        client.post(f"/api/videos/{video}/external-clips", json={"vendor": "klap"})
        drain(Worker("w"), limit=3)
    finally:
        ec.set_transport(None)
    with session_scope() as s:
        c = s.scalar(select(Clip).where(Clip.video_id == video))
        assert c.title == "Lease secrets" and c.score == 72 and c.engine == "klap"


def test_needs_key_and_public_address(client, video, monkeypatch):
    assert client.post(f"/api/videos/{video}/external-clips", json={"vendor": "klap"}).status_code == 409
    monkeypatch.setattr(get_settings(), "klap_api_key", "kl")
    monkeypatch.setattr(get_settings(), "public_media_url", None)
    r = client.post(f"/api/videos/{video}/external-clips", json={"vendor": "klap"})
    assert r.status_code == 409 and "CLIPSTAR_PUBLIC_MEDIA_URL" in r.json()["detail"]
    assert client.post(f"/api/videos/{video}/external-clips", json={"vendor": "opusclip"}).status_code == 422
