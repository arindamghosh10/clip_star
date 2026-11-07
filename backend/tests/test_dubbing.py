import subprocess
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from clipstar import dubbing
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.media import probe
from clipstar.models import Asset, Clip, ClipStatus, Video, VideoStatus, Workspace
from clipstar.pipeline import register_all
from clipstar.pipeline.framing import Layout
from clipstar.storage import get_storage
from clipstar.worker import Worker

from .conftest import drain

SRT = "1\n00:00:00,200 --> 00:00:01,800\nRevisa tu contrato.\n\n2\n00:00:02,000 --> 00:00:03,500\nNadie te lo dice.\n"


@pytest.fixture
def eleven(tmp_path, monkeypatch, client):
    register_all()
    client.get("/api/workspace")
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "el_key")
    monkeypatch.setattr(dubbing, "POLL_S", 0)
    mp3 = tmp_path / "dub.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=4", "-y", str(mp3)], check=True)
    states = iter(["dubbing", "dubbed"])
    calls = []

    def h(req):
        calls.append(req)
        p = req.url.path
        if p == "/v1/dubbing" and req.method == "POST":
            return httpx.Response(200, json={"dubbing_id": "d1", "expected_duration_sec": 10})
        if p == "/v1/dubbing/d1":
            return httpx.Response(200, json={"dubbing_id": "d1", "status": next(states, "dubbed")})
        if p == "/v1/dubbing/d1/audio/es":
            return httpx.Response(200, content=mp3.read_bytes(), headers={"content-type": "audio/mpeg"})
        if p == "/v1/dubbing/d1/transcript/es":
            return httpx.Response(200, text=SRT)
        return httpx.Response(404)

    dubbing.set_transport(httpx.MockTransport(h))
    yield calls
    dubbing.set_transport(None)


def make_clip(tmp_path):
    st = get_storage()
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="a.mp4", duration_s=8, status=VideoStatus.ready, meta={"probe": {"width": 640, "height": 360, "has_audio": True}})
        s.add(v)
        s.flush()
        rel = st.rel(v.id, "master.mp4")
        st.abs(rel).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8", "-f", "lavfi", "-i", "sine=duration=8", "-shortest", "-pix_fmt", "yuv420p", "-y", str(st.abs(rel))], check=True)
        s.add(Asset(video_id=v.id, kind="master", path=rel, size_bytes=1))
        s.add(Asset(video_id=v.id, kind="proxy", path=rel, size_bytes=1))
        c = Clip(video_id=v.id, title="Lease", start_s=1, end_s=5, score=70, status=ClipStatus.approved, variants=[{"id": "A", "hook": "CHECK IT", "caption_style": "bold-pop"}], meta={"words": [{"start": 0.2, "end": 0.6, "word": "Check"}], "renders": {}})
        s.add(c)
        s.flush()
        return str(c.id)


def test_dub_creates_rendered_language_version(client, eleven, tmp_path):
    cid = make_clip(tmp_path)
    r = client.post(f"/api/clips/{cid}/dubs", json={"lang": "es", "variant": "A"})
    assert r.status_code == 202 and r.json()["variant"] == "A-es"
    drain(Worker("w"), limit=6)
    up = eleven[0]
    assert up.headers["xi-api-key"] == "el_key" and b'name="target_lang"' in up.content and b"es" in up.content
    with session_scope() as s:
        c = s.get(Clip, cid)
        d = c.meta["dubs"]["A-es"]
        assert c.meta["ai_content"] is True and d["lang"] == "es" and [w["word"] for w in d["words"]][:3] == ["Revisa", "tu", "contrato."]
        r = c.meta["renders"]["A-es"]
        path = get_storage().abs(r["path"])
    info = probe(path)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio and abs(info.duration_s - 4) < 0.6
    # the Spanish account gets the dub, the English one the original
    es = client.post("/api/accounts", json={"platform": "instagram", "handle": "@es", "language": "Spanish"}).json()
    en = client.post("/api/accounts", json={"platform": "instagram", "handle": "@en", "language": "English"}).json()
    client.patch("/api/workspace", json={"settings": {"quiet_hours": False, "spacing_minutes": 0}})
    with session_scope() as s:
        c = s.get(Clip, cid)
        meta = dict(c.meta)
        vid = get_storage().abs(meta["renders"]["A-es"]["path"])
        meta["renders"]["A"] = {**meta["renders"]["A-es"]}  # pretend A is rendered too (it was, alongside)
        meta["preflight"] = {}
        c.meta = meta
    pv = client.post("/api/batches/preview", json={"name": "B", "clip_ids": [cid], "account_ids": [es["id"], en["id"]], "start_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}).json()
    got = {p["handle"]: p["variant"] for p in pv["posts"]}
    assert got == {"@es": "A-es", "@en": "A"}
    assert client.delete(f"/api/clips/{cid}/dubs/A-es").status_code == 204
    with session_scope() as s:
        assert "A-es" not in s.get(Clip, cid).meta.get("dubs", {})


def test_dubbing_needs_key_and_valid_language(client, tmp_path):
    client.get("/api/workspace")
    cid = make_clip(tmp_path)
    assert client.post(f"/api/clips/{cid}/dubs", json={"lang": "es"}).status_code == 409
    assert client.get("/api/dubbing").json()["enabled"] is False
