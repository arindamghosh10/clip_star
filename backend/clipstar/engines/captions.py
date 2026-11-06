"""Engine that uses a captions file (.srt / .vtt) uploaded with the video. Exact text, no model needed."""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import PermanentError
from ..models import Stage
from .base import EngineInfo, Segment, Transcript, Word

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE = re.compile(rf"{_TS}\s*-->\s*{_TS}")
_TAG = re.compile(r"<[^>]+>|\{[^}]+\}")


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_captions(text: str) -> list[tuple[float, float, str]]:
    """Parse SRT or WebVTT into (start, end, text) cues."""
    cues: list[tuple[float, float, str]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        m = _CUE.search(lines[i])
        if not m:
            i += 1
            continue
        g = m.groups()
        start, end = _secs(*g[:4]), _secs(*g[4:])
        i += 1
        body = []
        while i < len(lines) and lines[i].strip():
            if _CUE.search(lines[i]):
                break
            body.append(_TAG.sub("", lines[i]).strip())
            i += 1
        t = " ".join(x for x in body if x)
        if t and end > start:
            cues.append((start, end, t))
    return cues


def cues_to_segments(cues: list[tuple[float, float, str]]) -> list[Segment]:
    """Spread each cue's words evenly over its time span (weighted by word length)."""
    segs = []
    for start, end, text in cues:
        tokens = text.split()
        weights = [max(1, len(t)) for t in tokens]
        total = sum(weights)
        span = end - start
        t = start
        words = []
        for tok, wgt in zip(tokens, weights):
            dur = span * wgt / total
            words.append(Word(start=round(t, 3), end=round(t + dur, 3), word=tok))
            t += dur
        segs.append(Segment(start=start, end=end, text=text, words=words))
    return segs


class CaptionsFileEngine:
    info = EngineInfo(
        id="captions-file",
        stage=Stage.understand,
        name="Your captions file",
        kind="free",
        description="Uses the .srt or .vtt file uploaded with the video. Exact words; word timings are estimated.",
    )

    def check(self):
        from .base import Health

        return Health(True)

    def estimate(self, duration_s: float):
        return None

    def from_file(self, path: Path, duration_s: float) -> Transcript:
        try:
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            raise PermanentError(str(e), user_message="The captions file couldn't be read.") from e
        cues = parse_captions(raw)
        if not cues:
            raise PermanentError("no cues", user_message="The captions file has no readable captions.")
        return Transcript(engine=self.info.id, duration=duration_s, words_estimated=True, segments=cues_to_segments(cues))
