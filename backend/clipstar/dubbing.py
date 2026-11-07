"""Dub a clip into another language with ElevenLabs (your own API key; you pay ElevenLabs).

The clip's own audio (no captions burned in) goes to ElevenLabs; the dubbed audio and the translated
transcript come back, and the clip gets an extra version, e.g. "A-es", rendered with the dubbed voice and
captions in that language. Accounts set to that language post the dubbed version.
Dubbed clips are always marked as AI-altered (the voice is synthetic).

API (ElevenLabs docs): POST /v1/dubbing (multipart: file, target_lang, source_lang, num_speakers) -> dubbing_id;
GET /v1/dubbing/{id} until status is "dubbed"; GET /v1/dubbing/{id}/audio/{lang};
GET /v1/dubbing/{id}/transcript/{lang}?format_type=srt.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import budget
from .config import get_settings
from .errors import PermanentError, RetryableError
from .media import run_ffmpeg

KIND = "clip.dub"
BASE = "https://api.elevenlabs.io/v1"
POLL_S = 5.0
LANGS = {
    "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German", "it": "Italian", "hi": "Hindi", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "ar": "Arabic", "ru": "Russian", "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "id": "Indonesian", "vi": "Vietnamese",
    "fil": "Filipino", "sv": "Swedish", "uk": "Ukrainian", "ta": "Tamil", "en": "English",
}

_transport: httpx.BaseTransport | None = None  # tests use a fake ElevenLabs


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def enabled() -> bool:
    return bool(get_settings().elevenlabs_api_key)


def _check(r: httpx.Response) -> None:
    if r.status_code in (401, 403):
        raise PermanentError(r.text[:300], user_message="ElevenLabs rejected the API key.")
    if r.status_code == 402 or "quota" in r.text.lower():
        if r.status_code >= 400:
            raise PermanentError(r.text[:300], user_message="ElevenLabs says the account is out of credit for dubbing.")
    if r.status_code in (425, 429) or r.status_code >= 500:
        raise RetryableError(r.text[:300], user_message=f"ElevenLabs is busy ({r.status_code}); will retry.")
    if r.status_code >= 400:
        raise PermanentError(r.text[:300], user_message=f"ElevenLabs refused the dub ({r.status_code}): {r.text[:160]}")


def dub_audio(audio: Path, lang: str, duration_s: float, check=None, on_progress=None) -> tuple[bytes, str, str]:
    """Returns (dubbed audio bytes, content type, SRT transcript)."""
    st = get_settings()
    from .engines.llm import EngineDeclined

    try:
        budget.check("elevenlabs")
    except EngineDeclined as e:
        raise PermanentError(str(e), user_message=f"Dubbing skipped: {e}.") from e
    h = {"xi-api-key": st.elevenlabs_api_key or ""}
    with httpx.Client(timeout=300, transport=_transport, follow_redirects=True) as c:
        try:
            with audio.open("rb") as f:
                r = c.post(f"{BASE}/dubbing", headers=h, files={"file": (audio.name, f, "audio/mp4")}, data={"target_lang": lang, "source_lang": "auto", "num_speakers": "0"})
            _check(r)
            did = r.json()["dubbing_id"]
            deadline = time.monotonic() + max(900, duration_s * 20)
            while True:
                if check:
                    check()
                g = c.get(f"{BASE}/dubbing/{did}", headers=h)
                _check(g)
                d = g.json()
                status = str(d.get("status", "")).lower()
                if status == "dubbed":
                    break
                if status == "failed":
                    raise PermanentError(str(d), user_message=f"ElevenLabs couldn't dub this clip: {d.get('error') or 'failed'}")
                if time.monotonic() > deadline:
                    raise RetryableError("timeout", user_message="ElevenLabs is taking too long; will check again.")
                if on_progress:
                    on_progress(50)
                time.sleep(POLL_S)
            a = c.get(f"{BASE}/dubbing/{did}/audio/{lang}", headers=h)
            _check(a)
            t = c.get(f"{BASE}/dubbing/{did}/transcript/{lang}", headers=h, params={"format_type": "srt"})
            _check(t)
        except httpx.HTTPError as e:
            raise RetryableError(str(e), user_message="Couldn't reach ElevenLabs; will retry.") from e
    budget.charge("elevenlabs", 0, 0, round(duration_s / 60 * (st.elevenlabs_price_per_min or 0), 6))
    return a.content, a.headers.get("content-type", "audio/mpeg"), t.text


def srt_words(srt: str, duration: float) -> list[dict]:
    from .engines.captions import CaptionsFileEngine

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "dub.srt"
        p.write_text(srt, encoding="utf-8")
        tr = CaptionsFileEngine().from_file(p, duration)
    return [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for s in tr.segments for w in s.words]


def run_dub(ctx) -> dict:
    from sqlalchemy import select

    from .db import session_scope
    from .models import Asset, Clip
    from .storage import get_storage

    cid = uuid.UUID(ctx.payload["clip_id"])
    lang, base = ctx.payload["lang"], ctx.payload["variant"]
    st = get_storage()
    with session_scope() as s:
        c = s.get(Clip, cid)
        if c is None:
            return {"skipped": "clip deleted"}
        master = s.scalar(select(Asset).where(Asset.video_id == c.video_id, Asset.kind == "master"))
        if master is None or not st.exists(master.path):
            raise PermanentError("no master", user_message="The original video file is gone (archived?), so this clip can't be dubbed.")
        a, b, vid = c.start_s, c.end_s, c.video_id
        src = st.abs(master.path)
    dur = b - a
    with tempfile.TemporaryDirectory(prefix="clipstar-dub-") as tmp:
        clip_audio = Path(tmp) / "clip.m4a"
        run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-vn", "-ac", "2", "-c:a", "aac", "-b:a", "160k", "-y", str(clip_audio)], timeout_s=300)
        ctx.progress(10, f"Dubbing into {LANGS.get(lang, lang)} with ElevenLabs")
        audio, ctype, srt = dub_audio(clip_audio, lang, dur, ctx.check, lambda p: ctx.progress(p))
    ext = ".mp4" if "mp4" in ctype else ".wav" if "wav" in ctype else ".mp3"
    rel = st.rel(vid, f"clips/{cid}/dub-{base}-{lang}{ext}")
    tmpf = st.tmp_path_for(rel)
    try:
        tmpf.write_bytes(audio)
        st.commit_tmp(tmpf, rel)
    finally:
        if tmpf.exists():
            tmpf.unlink()
    words = srt_words(srt, dur)
    return {"variant_id": f"{base}-{lang}", "lang": lang, "base": base, "audio": rel, "words": words}


def _done(s, job, result: dict) -> None:
    from .models import Clip, ClipStatus
    from .pipeline.stages import enqueue_clip_render

    if "variant_id" not in result:
        return
    c = s.get(Clip, uuid.UUID(job.payload["clip_id"]), with_for_update=True)
    if c is None:
        return
    meta = dict(c.meta or {})
    dubs = dict(meta.get("dubs") or {})
    dubs[result["variant_id"]] = {"lang": result["lang"], "base": result["base"], "audio": result["audio"], "words": result["words"], "created_at": datetime.now(timezone.utc).isoformat()}
    meta["dubs"] = dubs
    meta["ai_content"] = True  # synthetic voice: always disclosed
    c.meta = meta
    if c.status != ClipStatus.rejected:
        enqueue_clip_render(s, c)


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(KIND, Handler(run=run_dub, on_success=_done))
