from types import SimpleNamespace

import pytest

from clipstar.db import session_scope
from clipstar.engines.captions import parse_captions
from clipstar.engines.whisper import WhisperEngine
from clipstar.models import Job, JobStatus, Stage, Video, VideoStatus
from clipstar.pipeline import register_all
from clipstar.worker import Worker

from .conftest import SAMPLE_SRT, drain


@pytest.fixture(autouse=True)
def _handlers():
    register_all()


def _upload(client, video, srt=None, title="Ep. 1"):
    files = {"file": ("ep1.mp4", open(video, "rb"), "video/mp4")}
    if srt:
        files["captions"] = ("ep1.srt", open(srt, "rb"), "text/plain")
    r = client.post("/api/videos", files=files, data={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def test_full_ingest_and_understand_with_captions(client, sample_video, sample_srt):
    v = _upload(client, sample_video, sample_srt)
    assert v["status"] == "queued" and v["active_job_id"]
    ran = drain(Worker("w"))
    assert ran == 5  # ingest, understand, moments, edit, package (12 s video: too short for a clip)

    v = client.get(f"/api/videos/{v['id']}").json()
    assert v["status"] == "ready", v
    assert abs(v["duration_s"] - 12) < 0.5
    kinds = {a["kind"] for a in v["assets"]}
    assert {"master", "captions", "proxy", "audio", "transcript", "scenes", "energy"} <= kinds
    u = v["meta"]["understand"]
    assert u["transcript_engine"] == "captions-file" and u["words"] == 23 and u["words_estimated"] is True

    tr = client.get(f"/api/videos/{v['id']}/transcript").json()
    words = [w for s in tr["segments"] for w in s["words"]]
    assert words[0]["word"] == "Nobody" and all(0 <= w["start"] <= w["end"] <= 12 for w in words)

    an = client.get(f"/api/videos/{v['id']}/analysis").json()
    assert any(5 < c < 7 for c in an["scenes"]["cuts"]), an["scenes"]  # the cut at 6 s
    assert any(7.5 <= p <= 9.5 for p in an["energy"]["peaks"]), an["energy"]["peaks"]  # loud burst at 8-9 s

    assert client.get(f"/api/videos/{v['id']}/proxy").status_code == 200


def test_missing_whisper_fails_with_clear_message_then_retry_works(client, sample_video, monkeypatch):
    v = _upload(client, sample_video)
    from clipstar.engines import registry
    from clipstar.engines.base import Health

    monkeypatch.setattr(registry.get_engine(Stage.understand, "faster-whisper"), "check", lambda: Health(False, "Not installed."))
    drain(Worker("w"))
    v = client.get(f"/api/videos/{v['id']}").json()
    assert v["status"] == "failed" and v["stage"] == "understand"
    assert "Not installed" in v["error"]

    # pretend it's installed now, with a fake model
    fake_seg = SimpleNamespace(start=0.5, end=3.0, text=" Hello there", words=[SimpleNamespace(start=0.5, end=1.0, word=" Hello", probability=0.9), SimpleNamespace(start=1.1, end=3.0, word=" there", probability=0.8)])

    class FakeModel:
        def transcribe(self, path, **kw):
            return iter([fake_seg]), SimpleNamespace(language="en")

    monkeypatch.setattr(registry.get_engine(Stage.understand, "faster-whisper"), "check", lambda: Health(True))
    orig = WhisperEngine.transcribe
    monkeypatch.setattr(WhisperEngine, "transcribe", lambda self, ctx, a, d, p: orig(self, ctx, a, d, p, model=FakeModel()))
    assert client.post(f"/api/videos/{v['id']}/retry").status_code == 200
    drain(Worker("w"))
    v = client.get(f"/api/videos/{v['id']}").json()
    assert v["status"] == "ready" and v["meta"]["understand"]["language"] == "en" and v["meta"]["understand"]["words"] == 2


def test_broken_file_fails_permanently_with_friendly_error(client, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    r = client.post("/api/videos", files={"file": ("bad.mp4", open(bad, "rb"), "video/mp4")})
    vid = r.json()["id"]
    drain(Worker("w"))
    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "failed" and "couldn't be read" in v["error"]
    with session_scope() as s:
        job = s.query(Job).filter(Job.video_id == vid).one()
        assert job.status == JobStatus.failed and job.attempts == 1  # permanent: no pointless retries


def test_rejects_wrong_file_type_and_empty_file(client, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hi")
    assert client.post("/api/videos", files={"file": ("notes.txt", open(p, "rb"))}).status_code == 422
    e = tmp_path / "empty.mp4"
    e.write_bytes(b"")
    assert client.post("/api/videos", files={"file": ("empty.mp4", open(e, "rb"))}).status_code == 422
    assert client.get("/api/videos").json() == []


def test_cancel_and_delete(client, sample_video):
    v = _upload(client, sample_video)
    assert client.post(f"/api/videos/{v['id']}/cancel").json()["status"] == "cancelled"
    assert drain(Worker("w")) == 0
    assert client.delete(f"/api/videos/{v['id']}").status_code == 204
    assert client.get(f"/api/videos/{v['id']}").status_code == 404
    with session_scope() as s:
        assert s.query(Video).count() == 0


def test_parse_vtt_and_srt():
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.500 align:start\n<v Maya>Hello <b>world</b>\n\n01:00:00.000 --> 01:00:01.000\nLate line\n"
    cues = parse_captions(vtt)
    assert cues == [(1.0, 2.5, "Hello world"), (3600.0, 3601.0, "Late line")]
    assert len(parse_captions(SAMPLE_SRT)) == 3
