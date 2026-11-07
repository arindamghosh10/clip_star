import socket
import subprocess

import httpx
import pytest
from sqlalchemy import select

from clipstar import importer
from clipstar.db import session_scope
from clipstar.importer import normalize
from clipstar.models import Asset, Job, Video
from clipstar.pipeline import register_all
from clipstar.worker import Worker

from .conftest import drain


@pytest.fixture(scope="module")
def mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("imp") / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2", "-pix_fmt", "yuv420p", "-y", str(p)], check=True)
    return p.read_bytes()


@pytest.fixture
def server(monkeypatch, mp4):
    real = socket.getaddrinfo

    def fake_dns(host, *a, **k):
        ip = "10.0.0.7" if host == "nas.lan.example.com" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        p = req.url.path
        if req.url.host == "files.example.com" and p == "/ep1.mp4":
            return httpx.Response(200, content=mp4, headers={"content-type": "video/mp4", "content-length": str(len(mp4))})
        if p == "/go":
            return httpx.Response(302, headers={"location": "https://files.example.com/ep1.mp4"})
        if p == "/to-nas":
            return httpx.Response(302, headers={"location": "https://nas.lan.example.com/x.mp4"})
        if p == "/page":
            return httpx.Response(200, text="<html>sign in</html>", headers={"content-type": "text/html"})
        if p == "/private.mp4":
            return httpx.Response(403)
        if req.url.host == "drive.usercontent.google.com":
            return httpx.Response(200, content=mp4, headers={"content-type": "application/octet-stream", "content-disposition": 'attachment; filename="Episode 12.mov"'})
        return httpx.Response(404)

    importer.set_transport(httpx.MockTransport(handler))
    yield seen
    importer.set_transport(None)


def test_normalize_links():
    assert normalize("https://www.dropbox.com/scl/fi/abc/ep.mp4?rlkey=k&dl=0")[0].endswith("rlkey=k&dl=1")
    assert normalize("https://drive.google.com/file/d/1AbCdEfGhIjKlMn/view?usp=sharing") == ("https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMn&export=download&confirm=t", "google-drive")
    for bad in ("https://www.youtube.com/watch?v=x", "https://youtu.be/x", "https://www.tiktok.com/@a/video/1", "ftp://x.com/a.mp4"):
        with pytest.raises(ValueError):
            normalize(bad)
    with pytest.raises(ValueError, match="doesn't point to a file"):
        normalize("https://drive.google.com/drive/folders/")


def run_import(client, url):
    register_all()
    r = client.post("/api/videos/import", json={"url": url})
    assert r.status_code == 201, r.text
    drain(Worker("w"), limit=2)
    with session_scope() as s:
        return s.get(Video, r.json()["id"]), s.scalar(select(Asset).where(Asset.video_id == r.json()["id"], Asset.kind == "master")), s.scalar(select(Job).where(Job.kind == "video.import"))


def test_direct_link_with_redirect_starts_processing(client, server):
    v, master, job = run_import(client, "https://short.example.com/go")
    assert master is not None and master.path.endswith("master.mp4") and v.title == "ep1" and v.status.value in ("queued", "processing", "ready")
    with session_scope() as s:
        assert s.scalar(select(Job).where(Job.kind == "pipeline.stage", Job.video_id == v.id)) is not None


def test_google_drive_filename(client, server):
    v, master, _ = run_import(client, "https://drive.google.com/file/d/1AbCdEfGhIjKlMn/view")
    assert master.path.endswith("master.mov") and v.title == "Episode 12" and v.source_filename == "Episode 12.mov"


@pytest.mark.parametrize(
    "url,msg",
    [
        ("https://files.example.com/page", "web page"),
        ("https://files.example.com/private.mp4", "isn't public"),
        ("https://files.example.com/nothing.mp4", "Nothing was found"),
        ("https://short.example.com/to-nas", "private or internal"),
    ],
)
def test_refusals_explain_themselves(client, server, url, msg):
    v, master, job = run_import(client, url)
    assert master is None and v.status.value == "failed" and msg in (v.error or "")


def test_bad_links_refused_up_front(client):
    client.get("/api/workspace")
    r = client.post("/api/videos/import", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert r.status_code == 422 and "against their terms" in r.json()["detail"]
