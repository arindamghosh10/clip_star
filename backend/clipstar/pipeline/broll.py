"""B-roll cutaways from Pexels (free stock video; your own Pexels API key).

Up to two short cutaways per clip, at moments where something concrete is said, never in the first
3 seconds (the hook) or the last 2. The voice and captions carry on over the cutaway.
API (Pexels docs): GET https://api.pexels.com/v1/videos/search?query=…&orientation=portrait,
header `Authorization: <key>`; each result has video_files[] with link, width, height.
Downloads are cached, so the same shot is fetched once.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..config import get_settings
from ..storage import get_storage

CUT_S = 2.0
MAX_CUTS = 2

_STOP = set(
    "about after again also always another because been before being between both could didn does doing down during each every from have having here into just like made make many more most much must never only other over really same should some still such than that their them then there these they thing things this those through very want were what when where which while with would your yours today going gonna actually people something everyone nothing".split()
)

_transport: httpx.BaseTransport | None = None  # tests use a fake Pexels


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def pick_moments(words: list[dict], duration: float) -> list[tuple[float, float, str]]:
    """(start, end, search term) for up to MAX_CUTS cutaways, spread out."""
    out: list[tuple[float, float, str]] = []
    for w in words:
        t = re.sub(r"[^a-z]", "", w["word"].lower())
        if len(t) < 5 or t in _STOP:
            continue
        a = round(w["start"], 3)
        if a < 3.0 or a + CUT_S > duration - 2.0:
            continue
        if out and a - out[-1][1] < 5.0:
            continue
        if any(term == t for _, _, term in out):
            continue
        out.append((a, round(a + CUT_S, 3), t))
        if len(out) >= MAX_CUTS:
            break
    return out


def _best_file(files: list[dict]) -> dict | None:
    portrait = [f for f in files if f.get("width") and f.get("height") and f["height"] > f["width"] and f.get("link")]
    if not portrait:
        return None
    good = [f for f in portrait if f["height"] >= 1280]
    return min(good, key=lambda f: f["height"]) if good else max(portrait, key=lambda f: f["height"])


def fetch(term: str) -> dict | None:
    """Find and cache one portrait shot for `term`. None if not set up, nothing found, or Pexels is unreachable."""
    st = get_settings()
    if not st.pexels_api_key:
        return None
    try:
        with httpx.Client(timeout=30, transport=_transport, follow_redirects=True) as c:
            r = c.get("https://api.pexels.com/v1/videos/search", params={"query": term, "orientation": "portrait", "per_page": 5}, headers={"Authorization": st.pexels_api_key})
            if r.status_code != 200:
                return None
            for v in r.json().get("videos") or []:
                f = _best_file(v.get("video_files") or [])
                if not f:
                    continue
                storage = get_storage()
                rel = f"broll/pexels-{v['id']}-{f['height']}.mp4"
                if not storage.exists(rel):
                    tmp = storage.tmp_path_for(rel)
                    try:
                        with c.stream("GET", f["link"]) as dl:
                            if dl.status_code != 200:
                                continue
                            with tmp.open("wb") as out:
                                for chunk in dl.iter_bytes(1024 * 1024):
                                    out.write(chunk)
                        storage.commit_tmp(tmp, rel)
                    finally:
                        if tmp.exists():
                            tmp.unlink()
                return {"path": str(storage.abs(rel)), "source": v.get("url"), "by": (v.get("user") or {}).get("name"), "id": v["id"]}
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return None


def plan_broll(words: list[dict], duration: float) -> list[dict]:
    """Cutaways ready for rendering: [{start, end, term, path, source, by, id}]."""
    out = []
    for a, b, term in pick_moments(words, duration):
        shot = fetch(term)
        if shot and Path(shot["path"]).exists():
            out.append({"start": a, "end": b, "term": term, **shot})
    return out
