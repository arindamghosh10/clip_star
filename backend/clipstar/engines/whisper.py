"""Free local transcription with faster-whisper (word-level timestamps). Install: pip install 'clipstar[whisper]'."""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

from ..config import get_settings
from ..errors import PermanentError, RetryableError
from ..jobs.runtime import JobContext
from ..models import Stage
from .base import EngineInfo, Health, Segment, Transcript, TranscriptionEngine, Word

_model_lock = threading.Lock()
_models: dict[tuple, object] = {}


def _load_model():
    st = get_settings()
    key = (st.whisper_model, st.whisper_device, st.whisper_compute_type)
    with _model_lock:
        if key not in _models:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise PermanentError("faster-whisper missing", user_message="The Whisper engine isn't installed. Run: pip install 'clipstar[whisper]', or pick another transcription engine.") from e
            try:
                _models[key] = WhisperModel(st.whisper_model, device=st.whisper_device, compute_type=st.whisper_compute_type)
            except Exception as e:  # model download / load problems are usually network or disk
                raise RetryableError(f"Whisper model load failed: {e}", user_message=f"Couldn't load the Whisper '{st.whisper_model}' model. Check the internet connection for the first download, and free disk space.") from e
        return _models[key]


class WhisperEngine(TranscriptionEngine):
    info = EngineInfo(
        id="faster-whisper",
        stage=Stage.understand,
        name="Whisper (local)",
        kind="free",
        description="Open-source speech recognition on your own machine, with word timings. Faster with a GPU.",
    )

    def check(self) -> Health:
        if importlib.util.find_spec("faster_whisper") is None:
            return Health(False, "Not installed. Run: pip install 'clipstar[whisper]'")
        return Health(True, f"Model: {get_settings().whisper_model}")

    def transcribe(self, ctx: JobContext, audio: Path, duration_s: float, on_progress, model=None) -> Transcript:
        model = model or _load_model()
        segments_iter, info = model.transcribe(str(audio), word_timestamps=True, vad_filter=True)
        segs: list[Segment] = []
        for seg in segments_iter:  # generator: transcription happens while iterating
            ctx.check()
            words = [Word(start=float(w.start), end=float(w.end), word=w.word.strip(), prob=float(getattr(w, "probability", 0) or 0)) for w in (seg.words or [])]
            segs.append(Segment(start=float(seg.start), end=float(seg.end), text=seg.text, words=words))
            if duration_s:
                on_progress(min(100.0, seg.end / duration_s * 100))
        return Transcript(engine=self.info.id, language=getattr(info, "language", None), duration=duration_s, segments=segs)
