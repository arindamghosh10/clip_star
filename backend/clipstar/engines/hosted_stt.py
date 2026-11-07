"""Hosted transcription connectors (your own API key, you pay the provider): Deepgram and AssemblyAI.

Both return word timings and speaker labels ("who said what"), which the transcript keeps per segment.
Request shapes follow the providers' public docs:
- Deepgram: POST https://api.deepgram.com/v1/listen?model=…&smart_format=true&diarize=true&utterances=true
  with `Authorization: Token <key>`; results.utterances[] (speaker, words) and results.channels[0].alternatives[0].words[].
- AssemblyAI: POST /v2/upload (raw bytes) -> upload_url; POST /v2/transcript {audio_url, speaker_labels, speech_models};
  poll GET /v2/transcript/{id} until status is "completed"; words/utterances times are in milliseconds.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .. import budget
from ..config import get_settings
from ..errors import PermanentError, RetryableError
from ..jobs.runtime import JobContext
from ..models import Stage
from .base import EngineInfo, Health, Segment, Transcript, TranscriptionEngine, Word
from .llm import EngineDeclined

_transport: httpx.BaseTransport | None = None  # tests use a fake provider


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def _client(timeout: float = 600) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=_transport)


def _raise_for(r: httpx.Response, name: str) -> None:
    if r.status_code in (401, 403):
        raise PermanentError(r.text[:300], user_message=f"{name} rejected the API key. Check it in your server settings.")
    if r.status_code == 402:
        raise PermanentError(r.text[:300], user_message=f"{name} says the account is out of credit.")
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(r.text[:300], user_message=f"{name} is busy or having trouble ({r.status_code}); will retry.")
    if r.status_code >= 400:
        raise PermanentError(r.text[:300], user_message=f"{name} refused the audio ({r.status_code}): {r.text[:160]}")


def _charge(engine: str, seconds: float, price_per_min: float | None) -> None:
    budget.charge(engine, 0, 0, round((seconds / 60) * (price_per_min or 0), 6))


def segments_from_words(words: list[tuple[float, float, str, str | None]], max_gap: float = 0.8, max_len: float = 12.0) -> list[Segment]:
    """Group (start, end, text, speaker) words into sentence-like segments; a new speaker always starts a segment."""
    segs: list[Segment] = []
    cur: list[tuple[float, float, str, str | None]] = []

    def flush():
        if cur:
            segs.append(Segment(start=cur[0][0], end=cur[-1][1], text=" ".join(w[2] for w in cur), speaker=cur[0][3], words=[Word(start=a, end=b, word=t) for a, b, t, _ in cur]))
            cur.clear()

    for w in words:
        if cur and (w[3] != cur[-1][3] or w[0] - cur[-1][1] > max_gap or w[1] - cur[0][0] > max_len):
            flush()
        cur.append(w)
        if w[2][-1:] in ".!?":
            flush()
    flush()
    return segs


class DeepgramEngine(TranscriptionEngine):
    info = EngineInfo(id="deepgram", stage=Stage.understand, name="Deepgram", kind="connector", description="Fast hosted speech recognition with speaker labels. Uses your Deepgram API key; you pay Deepgram per minute.")

    def check(self) -> Health:
        if not get_settings().deepgram_api_key:
            return Health(False, "No API key. Set CLIPSTAR_DEEPGRAM_API_KEY.")
        return Health(True, f"Model: {get_settings().deepgram_model}")

    def transcribe(self, ctx: JobContext, audio: Path, duration_s: float, on_progress, model=None) -> Transcript:
        st = get_settings()
        try:
            budget.check("deepgram")
        except EngineDeclined as e:
            raise PermanentError(str(e), user_message=f"Deepgram skipped: {e}. Pick a free transcription engine or raise the budget.") from e
        params = {"model": st.deepgram_model, "smart_format": "true", "punctuate": "true", "diarize": "true", "utterances": "true"}
        on_progress(5)
        with _client() as c, audio.open("rb") as f:
            try:
                r = c.post("https://api.deepgram.com/v1/listen", params=params, headers={"Authorization": f"Token {st.deepgram_api_key}", "Content-Type": "audio/wav"}, content=f.read())
            except httpx.HTTPError as e:
                raise RetryableError(str(e), user_message="Couldn't reach Deepgram; will retry.") from e
        _raise_for(r, "Deepgram")
        data = r.json()
        _charge("deepgram", duration_s, st.deepgram_price_per_min)
        res = data.get("results") or {}
        alt = ((res.get("channels") or [{}])[0].get("alternatives") or [{}])[0]
        words = [
            (float(w["start"]), float(w["end"]), str(w.get("punctuated_word") or w.get("word") or "").strip(), f"Speaker {int(w['speaker']) + 1}" if w.get("speaker") is not None else None)
            for w in alt.get("words") or []
            if (w.get("punctuated_word") or w.get("word"))
        ]
        lang = ((res.get("channels") or [{}])[0].get("detected_language")) or None
        on_progress(100)
        return Transcript(engine=self.info.id, language=lang, duration=duration_s, segments=segments_from_words(words))


class AssemblyAIEngine(TranscriptionEngine):
    info = EngineInfo(id="assemblyai", stage=Stage.understand, name="AssemblyAI", kind="connector", description="Hosted speech recognition with speaker labels. Uses your AssemblyAI API key; you pay AssemblyAI per hour of audio.")
    BASE = "https://api.assemblyai.com/v2"
    POLL_S = 3.0

    def check(self) -> Health:
        if not get_settings().assemblyai_api_key:
            return Health(False, "No API key. Set CLIPSTAR_ASSEMBLYAI_API_KEY.")
        return Health(True, f"Model: {get_settings().assemblyai_speech_model}")

    def transcribe(self, ctx: JobContext, audio: Path, duration_s: float, on_progress, model=None) -> Transcript:
        st = get_settings()
        try:
            budget.check("assemblyai")
        except EngineDeclined as e:
            raise PermanentError(str(e), user_message=f"AssemblyAI skipped: {e}. Pick a free transcription engine or raise the budget.") from e
        h = {"authorization": st.assemblyai_api_key or ""}
        with _client() as c:
            try:
                with audio.open("rb") as f:
                    up = c.post(f"{self.BASE}/upload", headers=h, content=f.read())
                _raise_for(up, "AssemblyAI")
                on_progress(10)
                job = c.post(f"{self.BASE}/transcript", headers=h, json={"audio_url": up.json()["upload_url"], "speaker_labels": True, "speech_models": [st.assemblyai_speech_model]})
                _raise_for(job, "AssemblyAI")
                tid = job.json()["id"]
                deadline = time.monotonic() + max(600, duration_s * 3)
                while True:
                    ctx.check()
                    g = c.get(f"{self.BASE}/transcript/{tid}", headers=h)
                    _raise_for(g, "AssemblyAI")
                    d = g.json()
                    if d.get("status") == "completed":
                        break
                    if d.get("status") == "error":
                        raise PermanentError(str(d.get("error")), user_message=f"AssemblyAI couldn't transcribe this: {d.get('error')}")
                    if time.monotonic() > deadline:
                        raise RetryableError("timeout", user_message="AssemblyAI is taking too long; will check again.")
                    on_progress(min(95.0, 10 + 85 * (1 - (deadline - time.monotonic()) / max(600, duration_s * 3))))
                    time.sleep(self.POLL_S)
            except httpx.HTTPError as e:
                raise RetryableError(str(e), user_message="Couldn't reach AssemblyAI; will retry.") from e
        _charge("assemblyai", duration_s, st.assemblyai_price_per_min)
        words = [(w["start"] / 1000, w["end"] / 1000, str(w.get("text", "")).strip(), f"Speaker {w['speaker']}" if w.get("speaker") else None) for w in d.get("words") or [] if w.get("text")]
        on_progress(100)
        return Transcript(engine=self.info.id, language=d.get("language_code"), duration=duration_s, segments=segments_from_words(words))
