import subprocess

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from clipstar.db import session_scope
from clipstar.models import Asset, Clip, ClipStatus, Job, Video, VideoStatus, Workspace
from clipstar.pipeline.transcript_edit import realign
from clipstar.storage import get_storage


@pytest.fixture(autouse=True)
def _ws(client):
    client.get("/api/workspace")


def setup_clip(render=True, status=ClipStatus.approved):
    st = get_storage()
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="a.mp4", duration_s=60, status=VideoStatus.ready)
        s.add(v)
        s.flush()
        tr = {"segments": [
            {"start": 0.0, "end": 2.0, "text": "check your lease", "words": [{"start": 0.0, "end": 0.5, "word": "check"}, {"start": 0.6, "end": 1.0, "word": "your"}, {"start": 1.1, "end": 2.0, "word": "lease"}]},
            {"start": 10.0, "end": 12.0, "text": "deposits matter", "words": [{"start": 10.0, "end": 11.0, "word": "deposits"}, {"start": 11.0, "end": 12.0, "word": "matter"}]},
        ]}
        rel = st.rel(v.id, "transcript.json")
        st.write_json(rel, tr)
        s.add(Asset(video_id=v.id, kind="transcript", path=rel, size_bytes=1))
        renders = {}
        if render:
            vid_rel = f"videos/{v.id}/clips/c/A.mp4"
            p = st.abs(vid_rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=270x480:rate=10:duration=3", "-pix_fmt", "yuv420p", "-y", str(p)], check=True)
            renders = {"A": {"path": vid_rel, "cover": None, "key": "k"}}
        c = Clip(video_id=v.id, title="Lease", start_s=0, end_s=3, score=70, status=status, variants=[{"id": "A", "hook": "", "caption_style": "bold-pop"}], meta={"renders": renders, "words": []})
        s.add(c)
        s.flush()
        return str(v.id), str(c.id)


def png(w=800, h=600):
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (0, 0, 255)
    return cv2.imencode(".png", img)[1].tobytes()


def test_upload_cover_fits_9x16_and_survives(client):
    _, cid = setup_clip()
    assert client.get(f"/api/clips/{cid}/cover/A").status_code == 404  # no auto cover in this fake render
    r = client.post(f"/api/clips/{cid}/cover/A", files={"file": ("c.png", png(), "image/png")})
    assert r.status_code == 200 and r.json()["custom"] is True
    got = client.get(f"/api/clips/{cid}/cover/A")
    img = cv2.imdecode(np.frombuffer(got.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (1920, 1080)
    assert client.post(f"/api/clips/{cid}/cover/A", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 422
    assert client.post(f"/api/clips/{cid}/cover/A", files={"file": ("t.png", png(100, 100), "image/png")}).status_code == 422
    assert client.post(f"/api/clips/{cid}/cover/Z", files={"file": ("c.png", png(), "image/png")}).status_code == 404
    # replacing deletes the old file; reset goes back to automatic
    with session_scope() as s:
        old = s.get(Clip, cid).meta["custom_covers"]["A"]
    client.post(f"/api/clips/{cid}/cover/A", files={"file": ("c.png", png(), "image/png")})
    assert not get_storage().abs(old).exists()
    assert client.delete(f"/api/clips/{cid}/cover/A").json()["custom"] is False


def test_cover_from_frame_and_publish_uses_it(client):
    _, cid = setup_clip()
    r = client.post(f"/api/clips/{cid}/cover/A/frame", json={"at_s": 1.5})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/clips/{cid}/cover/A").headers["content-type"] == "image/jpeg"
    assert client.post(f"/api/clips/{cid}/cover/A/frame", json={"at_s": 9}).status_code == 422
    from clipstar.pipeline.covers import cover_rel

    with session_scope() as s:
        c = s.get(Clip, cid)
        assert cover_rel(c, "A") == c.meta["custom_covers"]["A"]


def test_realign_keeps_or_spreads_timing():
    seg = {"start": 0.0, "end": 2.0, "words": [{"start": 0.0, "end": 0.5, "word": "a"}, {"start": 0.6, "end": 1.0, "word": "b"}]}
    assert [w["start"] for w in realign(seg, "x y")] == [0.0, 0.6]
    w = realign(seg, "one two three")
    assert w[0]["start"] == 0.0 and abs(w[-1]["end"] - 2.0) < 0.01 and all(x["estimated"] for x in w)


def test_edit_transcript_updates_overlapping_clips_only(client):
    vid, cid = setup_clip(render=False)
    r = client.put(f"/api/videos/{vid}/transcript/segments", json={"edits": [{"index": 0, "text": "check your rental lease"}]})
    assert r.status_code == 200 and r.json()["segments_changed"] == 1 and r.json()["clips_changed"] == 1
    tr = client.get(f"/api/videos/{vid}/transcript").json()
    assert tr["segments"][0]["text"] == "check your rental lease" and len(tr["segments"][0]["words"]) == 4
    with session_scope() as s:
        assert [w["word"] for w in s.get(Clip, cid).meta["words"]] == ["check", "your", "rental", "lease"]
        assert s.scalar(select(Job).where(Job.kind == "clip.render")) is not None
    # an edit outside the clip touches no clip; unchanged text is a no-op; bad input is refused
    assert client.put(f"/api/videos/{vid}/transcript/segments", json={"edits": [{"index": 1, "text": "deposits really matter"}]}).json()["clips_changed"] == 0
    assert client.put(f"/api/videos/{vid}/transcript/segments", json={"edits": [{"index": 1, "text": "deposits  really matter"}]}).json()["segments_changed"] == 0
    assert client.put(f"/api/videos/{vid}/transcript/segments", json={"edits": [{"index": 9, "text": "x"}]}).status_code == 422
    assert client.put(f"/api/videos/{vid}/transcript/segments", json={"edits": [{"index": 0, "text": "  "}]}).status_code == 422
