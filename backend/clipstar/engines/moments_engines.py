"""Engines for the Find moments stage.

- rules:  free, deterministic heuristics (always available, also the fallback).
- claude: Claude via the Anthropic API (your API key).
- ollama: a local model served by Ollama (free, runs on your machine).

AI engines return sentence-id ranges as JSON validated against a schema. Invalid output gets
one repair attempt; if the model still fails, is unreachable, or declines, the rules engine
runs instead and the clip notes say so. A temporary API problem retries the job first.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..errors import RetryableError
from ..jobs.runtime import JobContext
from ..models import Stage
from ..pipeline.moments import Candidate, MomentSettings, Sentence, Signals, _ts, energy_candidates, rules_candidates, score_window
from .base import EngineInfo, Health
from .llm import EngineDeclined, claude_health, claude_json, ollama_health, ollama_json

_EngineDeclined = EngineDeclined  # kept for older imports


class MomentEngine:
    info: EngineInfo

    def check(self) -> Health:
        return Health(True)

    def estimate(self, duration_s: float) -> str | None:
        return None

    def find(self, ctx: JobContext, sents: list[Sentence], sig: Signals, st: MomentSettings, duration: float) -> tuple[list[Candidate], list[str]]:
        raise NotImplementedError


class RulesMomentEngine(MomentEngine):
    info = EngineInfo(
        id="rules",
        stage=Stage.moments,
        name="Built-in rules",
        kind="free",
        description="Scores every complete-sentence window by hook, loudness, completeness and length. No AI, no cost.",
    )

    def find(self, ctx, sents, sig, st, duration):
        if not sents:
            return energy_candidates(sig, st, duration), ["No speech found, so moments were picked from the loudest parts of the video."]
        return rules_candidates(sents, sig, st, duration), []


# ---------- AI engines ----------


class AIClip(BaseModel):
    start_id: int = Field(ge=0)
    end_id: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=400)
    score: int = Field(ge=0, le=100)


class AIResult(BaseModel):
    clips: list[AIClip]


SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_id": {"type": "integer"},
                    "end_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_id", "end_id", "title", "hook", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM = """You are the clip editor for a video creator. You pick moments from a long video that work as standalone short videos (YouTube Shorts, Instagram Reels, TikTok).

A good clip:
- makes sense with no context from the rest of the video
- grabs attention in its first sentence (a bold claim, a question, a number, a surprising story)
- contains one clear idea and ends on a payoff or a complete thought
- is not an ad read, an intro, an outro, or housekeeping

Choose clips by sentence id ranges from the numbered transcript. Return only clips you would actually post, best first. If nothing in the transcript is worth posting, return an empty list."""


def build_prompt(sents: list[Sentence], sig: Signals, st: MomentSettings) -> str:
    lines = [f"[{s.id}] {_ts(s.start)}-{_ts(s.end)} {s.text}" for s in sents]
    profile = "\n".join(f"- {k}: {v}" for k, v in (("Niche", st.niche), ("Voice", st.voice), ("Audience", st.audience)) if v)
    banned = ", ".join(st.banned_topics)
    peaks = ", ".join(_ts(p) for p in sig.peaks[:40])
    return f"""<creator>
{profile or "- No profile set."}
- Never pick clips about: {banned or "(nothing banned)"}
</creator>

<rules>
- Each clip runs from the start of sentence start_id to the end of sentence end_id (inclusive).
- Each clip must last between {st.min_s:.0f} and {st.max_s:.0f} seconds; around {st.target_s:.0f} seconds is ideal. Use the timestamps to check.
- Clips must not overlap.
- Return at most {st.max_clips} clips.
- title: under 70 characters, written like a short-video title, no clickbait lies.
- hook: 2 to 5 words shown on screen in the first seconds.
- reason: one sentence on why this moment works.
- score: 0-100, how likely it is to perform well as a short.
</rules>

<loud_moments>{peaks or "none detected"}</loud_moments>

<transcript>
{chr(10).join(lines)}
</transcript>"""


def to_candidates(result: AIResult, sents: list[Sentence], sig: Signals, st: MomentSettings, engine: str) -> tuple[list[Candidate], list[str]]:
    """Turn model output into candidates, rejecting anything that doesn't match the transcript."""
    out: list[Candidate] = []
    problems: list[str] = []
    n = len(sents)
    for k, c in enumerate(result.clips):
        if c.start_id >= n or c.end_id >= n or c.end_id < c.start_id:
            problems.append(f"clip {k}: sentence ids {c.start_id}-{c.end_id} don't exist (valid 0-{n - 1})")
            continue
        dur = sents[c.end_id].end - sents[c.start_id].start
        if dur < st.min_s * 0.8 or dur > st.max_s * 1.15:
            problems.append(f"clip {k}: lasts {dur:.0f}s, must be {st.min_s:.0f}-{st.max_s:.0f}s")
            continue
        h = score_window(sents, c.start_id, c.end_id, sig, st)  # objective signals, for the blend and the UI
        out.append(
            Candidate(
                start_id=c.start_id,
                end_id=c.end_id,
                start=h.start,
                end=h.end,
                title=c.title.strip(),
                hook=c.hook.strip().upper(),
                reason=c.reason.strip(),
                score=round(0.75 * c.score + 0.25 * h.heuristic),
                heuristic=h.heuristic,
                features={**h.features, "ai_score": c.score},
                engine=engine,
            )
        )
    return out, problems


class AIMomentEngine(MomentEngine):
    """Shared flow: ask, validate, one repair attempt, else fall back to rules."""

    def call(self, system: str, prompt: str) -> str:
        raise NotImplementedError

    def find(self, ctx, sents, sig, st, duration):
        fallback = RulesMomentEngine()
        if not sents:
            c, n = fallback.find(ctx, sents, sig, st, duration)
            return c, n
        health = self.check()
        if not health.ok:
            c, n = fallback.find(ctx, sents, sig, st, duration)
            return c, [f"{self.info.name} isn't set up ({health.message}), so the built-in rules picked the moments.", *n]

        prompt = build_prompt(sents, sig, st)
        last_attempt = ctx.attempt >= get_settings().job_max_attempts
        try:
            ctx.progress(10, f"Asking {self.info.name} for moments")
            raw = self.call(SYSTEM, prompt)
            cands, problems = self._parse(raw, sents, sig, st)
            if problems and not cands:
                ctx.progress(50, "Fixing invalid answer")
                fix = f"{prompt}\n\nYour previous answer had these problems:\n- " + "\n- ".join(problems[:10]) + "\nReturn a corrected answer."
                cands, problems = self._parse(self.call(SYSTEM, fix), sents, sig, st)
        except RetryableError:
            if not last_attempt:
                raise  # temporary: let the job retry
            c, n = fallback.find(ctx, sents, sig, st, duration)
            return c, [f"{self.info.name} was unavailable after several tries, so the built-in rules picked the moments.", *n]
        except EngineDeclined as e:
            c, n = fallback.find(ctx, sents, sig, st, duration)
            return c, [f"{self.info.name}: {e}. The built-in rules picked the moments instead.", *n]

        if not cands:
            c, n = fallback.find(ctx, sents, sig, st, duration)
            why = f" ({problems[0]})" if problems else ""
            return c, [f"{self.info.name} didn't return usable moments{why}, so the built-in rules picked them.", *n]
        notes = [f"{len(problems)} suggested moment(s) were dropped because they didn't fit the rules."] if problems else []
        return cands, notes

    def _parse(self, raw: str, sents, sig, st) -> tuple[list[Candidate], list[str]]:
        try:
            result = AIResult.model_validate_json(raw)
        except ValidationError as e:
            return [], [f"answer didn't match the format: {e.errors()[0]['msg']}"]
        return to_candidates(result, sents, sig, st, self.info.id)


class ClaudeMomentEngine(AIMomentEngine):
    info = EngineInfo(
        id="claude",
        stage=Stage.moments,
        name="Claude",
        kind="connector",
        description="Claude reads the whole transcript and picks the moments, with titles and hooks. Uses your Anthropic API key.",
    )

    def check(self) -> Health:
        return claude_health()

    def estimate(self, duration_s: float) -> str | None:
        return "about $0.05 per 10 minutes of video (estimate)"

    def call(self, system: str, prompt: str) -> str:
        return claude_json(system, prompt, SCHEMA)


class OllamaMomentEngine(AIMomentEngine):
    info = EngineInfo(
        id="ollama",
        stage=Stage.moments,
        name="Local model (Ollama)",
        kind="free",
        description="A model running on your own machine with Ollama. Free and private; quality depends on the model.",
    )

    def check(self) -> Health:
        return ollama_health()

    def call(self, system: str, prompt: str) -> str:
        return ollama_json(system, prompt, SCHEMA)
