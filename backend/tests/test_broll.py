import subprocess

import httpx
import numpy as np
import pytest

from clipstar.config import get_settings
from clipstar.pipeline import broll
from clipstar.pipeline.framing import Layout
from clipstar.pipeline.render import RenderSpec, render_clip

from .test_render import _frame


def colour_clip(path, colour, size="720x1280", seconds=3):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:size={size}:rate=25:duration={seconds}", "-pix_fmt", "yuv420p", "-y", str(path)], check=True)
    return path


def test_pick_moments_avoids_hook_and_end():
    words = [{"start": 1.0, "end": 1.4, "word": "kitchen"}, {"start": 4.0, "end": 4.5, "word": "apartment"}, {"start": 6.0, "end": 6.5, "word": "landlord"}, {"start": 11.0, "end": 11.4, "word": "contract"}, {"start": 13.0, "end": 13.4, "word": "deposit"}]
    assert broll.pick_moments(words, 15) == [(4.0, 6.0, "apartment"), (11.0, 13.0, "contract")]


def test_fetch_picks_portrait_and_caches(tmp_path, monkeypatch, client):
    monkeypatch.setattr(get_settings(), "pexels_api_key", "px")
    clip = colour_clip(tmp_path / "red.mp4", "red").read_bytes()
    seen = []

    def h(req):
        seen.append(req)
        if req.url.path == "/v1/videos/search":
            return httpx.Response(200, json={"videos": [{"id": 42, "url": "https://www.pexels.com/video/42/", "user": {"name": "Ana"}, "video_files": [
                {"link": "https://videos.pexels.com/land.mp4", "width": 1920, "height": 1080},
                {"link": "https://videos.pexels.com/p-small.mp4", "width": 360, "height": 640},
                {"link": "https://videos.pexels.com/p-hd.mp4", "width": 1080, "height": 1920},
            ]}]})
        return httpx.Response(200, content=clip)

    broll.set_transport(httpx.MockTransport(h))
    try:
        shot = broll.fetch("apartment")
        assert shot["by"] == "Ana" and shot["path"].endswith("pexels-42-1920.mp4")
        assert seen[0].headers["authorization"] == "px" and seen[0].url.params["orientation"] == "portrait"
        assert str(seen[1].url) == "https://videos.pexels.com/p-hd.mp4"
        broll.fetch("apartment")
        assert len(seen) == 3  # search again, but the file comes from the cache
    finally:
        broll.set_transport(None)
    monkeypatch.setattr(get_settings(), "pexels_api_key", None)
    assert broll.fetch("x") is None


def test_cutaway_renders_fullscreen(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:size=1280x720:rate=25:duration=6", "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-pix_fmt", "yuv420p", "-y", str(src)], check=True)
    red = colour_clip(tmp_path / "red.mp4", "red")
    spec = RenderSpec(0, 6, [], "", "clean", Layout("scale", []), broll=[{"start": 2.0, "end": 4.0, "path": str(red), "id": 1}])
    out = tmp_path / "o.mp4"
    render_clip(src, 1280, 720, True, spec, out, tmp_path / "o.jpg", lambda p: None, lambda: None)
    mid = _frame(out, 3.0)[200:1700, 100:980].mean(axis=(0, 1))  # BGR
    before = _frame(out, 1.0)[900:1000, 400:600].mean(axis=(0, 1))
    after = _frame(out, 5.0)[900:1000, 400:600].mean(axis=(0, 1))
    assert mid[2] > 180 and mid[0] < 60  # red fills the frame during the cutaway
    assert before[0] > 150 and after[0] > 150  # blue speaker shot before and after
