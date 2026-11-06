"""Engines for the Package stage: titles, captions and hashtags per platform."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..errors import RetryableError
from ..jobs.runtime import JobContext
from ..models import Stage
from ..pipeline.package import PLATFORM_RULES, ClipContext, PackageSettings, template_copy
from .base import EngineInfo, Health
from .llm import EngineDeclined, claude_health, claude_json, ollama_health, ollama_json


class PackageEngine:
    info: EngineInfo

    def check(self) -> Health:
        return Health(True)

    def estimate(self, duration_s: float) -> str | None:
        return None

    def write(self, ctx: JobContext, clip: ClipContext, st: PackageSettings) -> tuple[dict, list[str]]:
        """Returns ({platform: {title, caption, hashtags}}, notes)."""
        raise NotImplementedError


class TemplatePackageEngine(PackageEngine):
    info = EngineInfo(
        id="templates",
        stage=Stage.package,
        name="Templates",
        kind="free",
        description="Builds each platform's caption from the clip title, its next sentence, your call to action and your hashtags. No AI, no cost.",
    )

    def write(self, ctx, clip, st):
        return {p: template_copy(clip, p, st) for p in st.platforms}, []


class _Copy(BaseModel):
    title: str = Field(default="", max_length=300)
    caption: str = Field(max_length=6000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


SYSTEM = """You write the post text for short video clips made from a creator's long video. Write in the creator's voice.
Never invent facts that aren't in the clip. No clickbait that the clip doesn't deliver on. No emojis unless the creator's voice uses them."""


def _schema(platforms: list[str]) -> dict:
    item = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "caption": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}}},
        "required": ["title", "caption", "hashtags"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {p: item for p in platforms}, "required": platforms, "additionalProperties": False}


def _prompt(clip: ClipContext, st: PackageSettings) -> str:
    rules = "\n".join(
        f"- {p} ({r['label']}): {r['style']} "
        + (f"Title up to {r['title_max']} characters. " if r["needs_title"] else 'Leave "title" empty. ')
        + f"Caption plus hashtags up to {r['caption_max']} characters. At most {r['hashtags_max']} hashtags, without the # sign."
        for p, r in PLATFORM_RULES.items()
        if p in st.platforms
    )
    profile = "\n".join(f"- {k}: {v}" for k, v in (("Niche", st.niche), ("Voice", st.voice), ("Audience", st.audience), ("Call to action", st.cta), ("Always-use hashtags", ", ".join(st.hashtags))) if v)
    return f"""<creator>
{profile or "- No profile set."}
- Never mention: {", ".join(st.banned_topics) or "(nothing banned)"}
</creator>

<clip>
Working title: {clip.title}
On-screen hook: {clip.hook}
Length: {clip.duration:.0f} seconds
What is said:
{clip.text}
</clip>

<platforms>
{rules}
</platforms>

Write the post text for each platform listed."""


class _AIPackageEngine(PackageEngine):
    def call(self, system: str, prompt: str, schema: dict) -> str:
        raise NotImplementedError

    def write(self, ctx, clip, st):
        fallback = TemplatePackageEngine()
        h = self.check()
        if not h.ok:
            c, _ = fallback.write(ctx, clip, st)
            return c, [f"{self.info.name} isn't set up ({h.message}), so templates wrote the captions."]
        last_attempt = ctx.attempt >= get_settings().job_max_attempts
        schema = _schema(st.platforms)
        prompt = _prompt(clip, st)
        try:
            raw = self.call(SYSTEM, prompt, schema)
            out, bad = self._parse(raw, st)
            if bad and not out:
                raw = self.call(SYSTEM, prompt + "\n\nYour previous answer was not valid JSON for the schema. Answer again.", schema)
                out, bad = self._parse(raw, st)
        except RetryableError:
            if not last_attempt:
                raise
            c, _ = fallback.write(ctx, clip, st)
            return c, [f"{self.info.name} was unavailable after several tries, so templates wrote the captions."]
        except EngineDeclined as e:
            c, _ = fallback.write(ctx, clip, st)
            return c, [f"{self.info.name}: {e}. Templates wrote the captions instead."]
        notes = []
        if bad:
            notes.append(f"{self.info.name} skipped {', '.join(bad)}; templates filled them in.")
        return out, notes  # missing platforms are filled with templates by finalize_copy

    def _parse(self, raw: str, st: PackageSettings) -> tuple[dict, list[str]]:
        import json

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {}, list(st.platforms)
        if not isinstance(data, dict):
            return {}, list(st.platforms)
        out, bad = {}, []
        for p in st.platforms:
            try:
                out[p] = _Copy.model_validate(data.get(p)).model_dump()
            except ValidationError:
                bad.append(p)
        return out, bad


class ClaudePackageEngine(_AIPackageEngine):
    info = EngineInfo(id="claude", stage=Stage.package, name="Claude", kind="connector", description="Claude writes each platform's title, caption and hashtags in your voice. Uses your Anthropic API key.")

    def check(self) -> Health:
        return claude_health()

    def estimate(self, duration_s: float) -> str | None:
        return "about $0.01 per clip (estimate)"

    def call(self, system, prompt, schema):
        return claude_json(system, prompt, schema, max_tokens=8000)


class OllamaPackageEngine(_AIPackageEngine):
    info = EngineInfo(id="ollama", stage=Stage.package, name="Local model (Ollama)", kind="free", description="A model on your own machine writes the captions. Free and private.")

    def check(self) -> Health:
        return ollama_health()

    def call(self, system, prompt, schema):
        return ollama_json(system, prompt, schema)
