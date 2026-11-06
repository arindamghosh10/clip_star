"""The plugin contract every engine follows, and the typed data stages pass around."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..jobs.runtime import JobContext
from ..models import Stage


@dataclass(frozen=True)
class EngineInfo:
    id: str
    stage: Stage
    name: str
    kind: Literal["free", "connector"]
    description: str


@dataclass
class Health:
    ok: bool
    message: str = ""


class Engine(ABC):
    info: EngineInfo

    def check(self) -> Health:
        """Is everything this engine needs present (binaries, models, credentials)?"""
        return Health(True)

    def estimate(self, duration_s: float) -> str | None:
        """Human-readable cost estimate for a video of this length, or None if free."""
        return None


# ---------- transcripts ----------


class Word(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    word: str
    prob: float | None = None


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None = None
    words: list[Word] = []


class Transcript(BaseModel):
    engine: str
    language: str | None = None
    duration: float = Field(ge=0)
    words_estimated: bool = False  # True when word timings were spread evenly (captions files)
    segments: list[Segment] = []

    @model_validator(mode="after")
    def _clean(self) -> "Transcript":
        """Never trust engine timings: clamp to the video, fix inverted ranges, sort, drop empties."""
        d = self.duration or float("inf")
        clean: list[Segment] = []
        for seg in sorted(self.segments, key=lambda x: x.start):
            seg.start = max(0.0, min(seg.start, d))
            seg.end = max(seg.start, min(seg.end, d))
            words = []
            for w in sorted(seg.words, key=lambda x: x.start):
                w.start = max(seg.start, min(w.start, seg.end))
                w.end = max(w.start, min(w.end, seg.end))
                if w.word.strip():
                    words.append(w)
            seg.words = words
            seg.text = seg.text.strip()
            if seg.text:
                clean.append(seg)
        self.segments = clean
        return self

    @property
    def word_count(self) -> int:
        return sum(len(s.words) if s.words else len(s.text.split()) for s in self.segments)


class TranscriptionEngine(Engine):
    @abstractmethod
    def transcribe(self, ctx: JobContext, audio: Path, duration_s: float, on_progress) -> Transcript: ...
