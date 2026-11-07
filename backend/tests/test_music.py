import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipstar.media import probe
from clipstar.pipeline.framing import Layout
from clipstar.pipeline.render import RenderSpec, render_clip

H = {"X-ClipStar": "1"}


def tone(path: Path, seconds=8, ext="mp3"):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-y", str(path)], check=True)
    return path


def silent_video(path: Path, seconds=6):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", str(seconds), "-shortest", "-y", str(path)], check=True)
    return path


def rms(path: Path, a: float, b: float) -> float:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a), "-t", str(b - a), "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float)
    return float(np.sqrt((x**2).mean())) if len(x) else 0.0


def test_library_upload_rules(client, tmp_path):
    client.get("/api/workspace")
    t = tone(tmp_path / "t.mp3")
    assert client.post("/api/music", files={"file": ("t.mp3", t.read_bytes(), "audio/mpeg")}, data={"title": "Lo-fi"}).status_code == 422  # rights not confirmed
    assert client.post("/api/music", files={"file": ("t.txt", b"hi", "text/plain")}, data={"confirm_rights": "true"}).status_code == 422
    assert client.post("/api/music", files={"file": ("fake.mp3", b"not audio at all", "audio/mpeg")}, data={"confirm_rights": "true"}).status_code == 422
    r = client.post("/api/music", files={"file": ("t.mp3", t.read_bytes(), "audio/mpeg")}, data={"title": "Lo-fi", "license_note": "Made it myself", "confirm_rights": "true"})
    assert r.status_code == 201, r.text
    tr = r.json()
    assert tr["title"] == "Lo-fi" and 7.5 < tr["duration_s"] < 8.5
    assert client.get(f"/api/music/{tr['id']}/audio").headers["content-type"] == "audio/mp4"
    assert [x["id"] for x in client.get("/api/music").json()] == [tr["id"]]
    assert client.delete(f"/api/music/{tr['id']}").status_code == 204
    assert client.get("/api/music").json() == []


def test_music_is_mixed_and_looped(tmp_path):
    src = silent_video(tmp_path / "v.mp4", 6)
    music = tmp_path / "m.m4a"
    from clipstar.pipeline.music import import_track

    assert 2.5 < import_track(tone(tmp_path / "short.mp3", 4), music) < 4.5  # shorter than the clip: it loops
    layout = Layout("fit", [])
    with_m = RenderSpec(0, 6, [], "", "clean", layout, music={"id": "t1", "path": str(music), "volume": 0.3, "offset": 0})
    without = RenderSpec(0, 6, [], "", "clean", layout)
    assert with_m.key() != without.key()
    o1, o2 = tmp_path / "with.mp4", tmp_path / "without.mp4"
    render_clip(src, 640, 360, True, with_m, o1, tmp_path / "a.jpg", lambda p: None, lambda: None)
    render_clip(src, 640, 360, True, without, o2, tmp_path / "b.jpg", lambda p: None, lambda: None)
    assert abs(probe(o1).duration_s - 6) < 0.5
    assert rms(o1, 1, 3) > 300 and rms(o2, 1, 3) < 50  # music audible under a silent voice
    assert rms(o1, 4.5, 5.0) > 300  # still playing after the 4 s track ended: looped


def test_variant_music_choice_saved(client, tmp_path):
    from .test_covers_transcript import setup_clip

    client.get("/api/workspace")
    _, cid = setup_clip(render=False)
    t = tone(tmp_path / "t.mp3")
    tr = client.post("/api/music", files={"file": ("t.mp3", t.read_bytes(), "audio/mpeg")}, data={"confirm_rights": "true"}).json()
    r = client.patch(f"/api/clips/{cid}", json={"variants": [{"id": "A", "caption_style": "bold-pop", "hook": "", "music": {"track_id": tr["id"], "volume": 0.2}}]})
    assert r.status_code == 200 and r.json()["variants"][0]["music"]["track_id"] == tr["id"]
    r = client.delete(f"/api/music/{tr['id']}")
    assert r.status_code == 409 and "1 clip version uses" in r.json()["detail"]
