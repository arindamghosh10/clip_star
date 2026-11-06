import subprocess

import pytest

from clipstar.db import session_scope
from clipstar.media import probe
from clipstar.models import Clip, Workspace
from clipstar.pipeline import register_all
from clipstar.pipeline import framing
from clipstar.pipeline.captions_ass import build_ass, group_lines, STYLES
from clipstar.pipeline.framing import Layout, plan_layout, video_filter
from clipstar.storage import get_storage
from clipstar.worker import Worker

from .conftest import _TMP, drain

LONG_SRT = "\n".join(
    f"{i + 1}\n00:00:{a:02d},000 --> 00:00:{b:02d},000\n{t}\n"
    for i, (a, b, t) in enumerate(
        [
            (1, 4, "Welcome back to the channel everyone."),
            (4, 8, "Today we have a guest with us."),
            (9, 12, "Nobody tells you this about rent?"),
            (12, 17, "I lost forty dollars a month for three years."),
            (17, 22, "Check your lease for the admin fee line."),
            (22, 26, "Ask them to remove it and save money."),
            (27, 31, "Thanks for watching and see you next week."),
        ]
    )
)


@pytest.fixture(autouse=True)
def _handlers():
    register_all()


@pytest.fixture(scope="module")
def talk_video():
    out = _TMP / "talk.mp4"
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=16",
             "-f", "lavfi", "-i", "smptebars=size=1280x720:rate=30:duration=16",
             "-f", "lavfi", "-i", "sine=frequency=300:duration=32",
             "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v];[2:a]volume='if(between(t,10,12),1,0.08)':eval=frame[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)],
            check=True,
        )
    return out


def _settings(client, **kw):
    client.patch("/api/workspace", json={"settings": {"clip_min_s": 8, "clip_max_s": 20, "clip_target_s": 14, **kw}})


def _upload(client, video, tmp_path):
    srt = tmp_path / "talk.srt"
    srt.write_text(LONG_SRT)
    r = client.post("/api/videos", files={"file": ("talk.mp4", open(video, "rb")), "captions": ("talk.srt", open(srt, "rb"))})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_full_pipeline_renders_vertical_clips_with_variants(client, talk_video, tmp_path):
    _settings(client)
    vid = _upload(client, talk_video, tmp_path)
    assert drain(Worker("w"), limit=10) == 5  # ingest, understand, moments, edit, package
    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "ready", v
    assert v["meta"]["moments"]["engine"] == "rules"
    clips = client.get("/api/clips", params={"video_id": vid}).json()
    assert clips, "expected at least one clip"
    top = clips[0]
    assert top["title"].startswith("Nobody tells you this") and 8 * 0.8 <= top["end_s"] - top["start_s"] <= 20 * 1.15
    assert [x["id"] for x in top["variants"]] == ["A", "B"]
    assert top["meta"]["words"][0]["word"] == "Nobody"
    for variant in ("A", "B"):
        r = top["meta"]["renders"][variant]
        assert r["layout"]["mode"] == "fit"  # no faces in a test pattern
        path = get_storage().abs(r["path"])
        info = probe(path)
        assert (info.width, info.height) == (1080, 1920) and info.has_audio
        assert abs(info.duration_s - (top["end_s"] - top["start_s"])) < 0.6
        m = client.get(f"/api/clips/{top['id']}/media/{variant}")
        assert m.status_code == 200 and m.headers["content-type"] == "video/mp4"
        assert client.get(f"/api/clips/{top['id']}/cover/{variant}").headers["content-type"] == "image/jpeg"

    # re-render: unchanged clip is skipped (resumable), a changed hook re-renders only that clip
    client.patch(f"/api/clips/{top['id']}", json={"status": "approved"})
    with session_scope() as s:
        c = s.get(Clip, top["id"])
        c.variants = [{**c.variants[0], "hook": "THE RENT TRAP"}, c.variants[1]]
    assert client.post(f"/api/clips/{top['id']}/render").status_code == 202
    drain(Worker("w"))
    jobs = client.get("/api/jobs", params={"video_id": vid}).json()
    rj = next(j for j in jobs if j["kind"] == "clip.render")
    assert rj["status"] == "succeeded"
    detail = client.get(f"/api/jobs/{rj['id']}").json()
    assert detail["result"] == {"rendered": 1, "failed": 0, "skipped": 1}


def test_rejected_clip_cannot_be_rerendered(client, talk_video, tmp_path):
    _settings(client, variants=1)
    vid = _upload(client, talk_video, tmp_path)
    drain(Worker("w"), limit=10)
    clip = client.get("/api/clips", params={"video_id": vid}).json()[0]
    assert [x["id"] for x in clip["variants"]] == ["A"]
    client.patch(f"/api/clips/{clip['id']}", json={"status": "rejected"})
    assert client.post(f"/api/clips/{clip['id']}/render").status_code == 409
    assert client.get(f"/api/clips/{clip['id']}/media/B").status_code == 404


def test_crop_layout_follows_face_per_scene_and_renders(talk_video, tmp_path):
    # fake detector: face on the right in the first scene, on the left in the second
    calls = {"n": 0}

    def det(frame):
        calls["n"] += 1
        return [(900, 200, 120, 120)] if calls["n"] <= 6 else [(150, 200, 120, 120)]

    layout = plan_layout(talk_video, 13.0, 19.0, [16.0], 1280, 720, detector=det)
    assert layout.mode == "crop" and len(layout.segments) == 2
    assert layout.segments[0][2] > 0.6 and layout.segments[1][2] < 0.3

    from clipstar.pipeline.render import RenderSpec, render_clip

    spec = RenderSpec(13.0, 19.0, [{"start": 0.2, "end": 0.8, "word": "Hello"}, {"start": 0.8, "end": 1.4, "word": "there."}], "HOOK", "bold-pop", layout)
    out, cover = tmp_path / "c.mp4", tmp_path / "c.jpg"
    info = render_clip(talk_video, 1280, 720, True, spec, out, cover, lambda p: None, lambda: None)
    assert out.exists() and cover.exists() and abs(info["duration_s"] - 6) < 0.6


def test_vertical_source_and_filters():
    assert plan_layout(None, 0, 10, [], 1080, 1920).mode == "scale"  # type: ignore[arg-type]
    f = video_filter(Layout("crop", [(0, 3, 0.9), (3, 6, 0.1)]), 1920, 1080, "/tmp/a b:c.ass")
    assert "crop=608:1080:if(lt(t\\,3.000)\\,1312\\,0):0" in f and "filename='/tmp/a b\\:c.ass'" in f


def test_ass_captions_highlight_each_word_and_escape_text():
    words = [{"start": 0, "end": 0.4, "word": "Nobody"}, {"start": 0.4, "end": 0.8, "word": "{tell}"}, {"start": 0.8, "end": 1.2, "word": "you."}, {"start": 3, "end": 3.5, "word": "Next"}]
    lines = group_lines(words, STYLES["bold-pop"])
    assert [len(l) for l in lines] == [3, 1]
    ass = build_ass(words, 5, "bold-pop", "rent trap", "DejaVu Sans")
    assert ass.count("Style: Cap") == 1 and "RENT TRAP" in ass and "{tell}" not in ass and "(TELL)" in ass
    assert ass.count("Dialogue: 0,") == 4  # one event per word in highlight mode


def test_package_and_clip_editing(client, talk_video, tmp_path):
    _settings(client, variants=1, auto_approve_score=60, platforms=["youtube", "x", "instagram"])
    vid = _upload(client, talk_video, tmp_path)
    drain(Worker("w"), limit=10)
    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "ready" and v["meta"]["package"]["engine"] == "templates"
    clip = client.get("/api/clips", params={"video_id": vid}).json()[0]
    assert set(clip["copy"]) == {"youtube", "x", "instagram"} and all(p["ok"] for p in clip["meta"]["preflight"].values())
    assert clip["status"] == ("approved" if clip["score"] >= 60 else "pending")

    # trim: words follow the new range and a re-render is queued
    r = client.patch(f"/api/clips/{clip['id']}", json={"start_s": clip["start_s"] + 3.0, "end_s": clip["end_s"]})
    assert r.status_code == 200, r.text
    c2 = r.json()
    assert c2["meta"]["words"][0]["word"] != clip["meta"]["words"][0]["word"] and c2["meta"]["words"][0]["start"] >= 0
    jobs = client.get("/api/jobs", params={"video_id": vid, "status": "queued"}).json()
    assert any(j["kind"] == "clip.render" for j in jobs)
    assert client.patch(f"/api/clips/{clip['id']}", json={"start_s": 0, "end_s": 1}).status_code == 422
    assert client.patch(f"/api/clips/{clip['id']}", json={"start_s": 0, "end_s": 999}).status_code == 422

    # variants and copy
    r = client.patch(f"/api/clips/{clip['id']}", json={"variants": [{"id": "A", "caption_style": "clean", "hook": "the rent trap"}, {"id": "B", "caption_style": "bold-pop", "hook": "x"}]}).json()
    assert r["variants"][0] == {"id": "A", "caption_style": "clean", "hook": "THE RENT TRAP"}
    assert client.patch(f"/api/clips/{clip['id']}", json={"variants": [{"id": "A"}, {"id": "A"}]}).status_code == 422
    r = client.patch(f"/api/clips/{clip['id']}", json={"copy": {"x": {"caption": "a" * 300, "hashtags": ["#Rent", "rent"]}}}).json()
    assert r["copy"]["x"]["hashtags"] == ["Rent"] and r["meta"]["copy_edited"] and not r["meta"]["preflight"]["x"]["ok"]
    assert r["copy"]["youtube"]["title"]  # other platforms kept
    assert client.patch(f"/api/clips/{clip['id']}", json={"copy": {"myspace": {"caption": "x"}}}).status_code == 422
    drain(Worker("w"))

    # fix a word everywhere
    r = client.post(f"/api/videos/{vid}/transcript/replace", json={"find": "lease", "replace": "rental contract"})
    assert r.status_code == 200 and r.json()["replaced"] >= 1, r.text
    tr = client.get(f"/api/videos/{vid}/transcript").json()
    assert "rental contract" in " ".join(s["text"] for s in tr["segments"]) and "lease" not in " ".join(s["text"] for s in tr["segments"]).lower()
    assert client.post(f"/api/videos/{vid}/transcript/replace", json={"find": "zebra", "replace": "x"}).status_code == 404
