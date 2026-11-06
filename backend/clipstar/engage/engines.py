"""Engines for the Engage stage: sort comments and draft replies.

AI output is validated: categories must be known, replies must fit the platform, contain no links
(unless they're in the creator's own lead reply), avoid banned topics, and spam never gets a reply.
Anything that fails falls back to the free rules for that comment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..config import get_settings
from ..engines.base import EngineInfo, Health
from ..engines.llm import EngineDeclined, claude_health, claude_json, ollama_health, ollama_json
from ..errors import RetryableError
from ..models import Stage
from ..pipeline.moments import mentions_banned
from .rules import CATEGORIES, EngageSettings, _URL, classify, template_reply


@dataclass
class CommentIn:
    id: str
    author: str
    text: str
    platform: str
    clip_title: str
    clip_text: str
    max_chars: int


@dataclass
class CommentOut:
    category: str
    draft: str
    by: str


def rules_result(c: CommentIn, st: EngageSettings) -> CommentOut:
    cat = classify(c.text)
    return CommentOut(cat, template_reply(cat, c.id, st)[: c.max_chars], "rules")


def clean_reply(text: str, c: CommentIn, st: EngageSettings) -> str | None:
    """Return a safe reply or None if it must be replaced."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    if _URL.search(t) and not (st.lead_reply and _URL.search(st.lead_reply) and t in st.lead_reply):
        return None
    if mentions_banned(t, st.banned_topics):
        return None
    if len(t) > c.max_chars:
        cut = t[: c.max_chars - 1].rsplit(" ", 1)[0]
        t = cut + "…"
    return t


class EngageEngine:
    info: EngineInfo

    def check(self) -> Health:
        return Health(True)

    def estimate(self, duration_s: float) -> str | None:
        return None

    def process(self, ctx, items: list[CommentIn], st: EngageSettings) -> tuple[dict[str, CommentOut], list[str]]:
        raise NotImplementedError


class RulesEngageEngine(EngageEngine):
    info = EngineInfo(id="rules", stage=Stage.engage, name="Built-in rules", kind="free", description="Sorts comments by keywords and drafts thank-you and contact replies from templates. Questions and criticism are left for you to answer.")

    def process(self, ctx, items, st):
        return {c.id: rules_result(c, st) for c in items}, []


SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "category": {"type": "string", "enum": list(CATEGORIES)}, "reply": {"type": "string"}},
                "required": ["id", "category", "reply"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM = """You help a video creator handle comments on their own short videos. For each comment, pick one category and draft a reply in the creator's voice.

Categories: question (asks something), lead (business, collaboration, sponsorship), praise (thanks, compliments), critical (disagrees or complains), spam (scams, self-promotion, links), other.

Replies:
- Short and human, like the creator typing on their phone. Match the comment's language.
- Answer questions only from what the clip says. If the clip doesn't answer it, say so honestly or say you'll cover it; never invent facts, numbers or promises.
- Critical comments: calm, no arguing, acknowledge, add one clarifying point from the clip if there is one.
- Leads: use the creator's contact line exactly as given.
- Spam: reply must be an empty string.
- No links, no hashtags, no asking for follows."""


def _prompt(items: list[CommentIn], st: EngageSettings) -> str:
    rows = "\n".join(
        json.dumps({"id": c.id, "platform": c.platform, "max_chars": c.max_chars, "clip": c.clip_title, "clip_says": c.clip_text[:1500], "author": c.author, "comment": c.text[:1000]}, ensure_ascii=False)
        for c in items
    )
    return f"""<creator>
- Niche: {st.niche or "not set"}
- Voice: {st.voice or "friendly and direct"}
- Contact line for business enquiries: {st.lead_reply}
- Never mention: {", ".join(st.banned_topics) or "(nothing banned)"}
</creator>

<comments>
{rows}
</comments>

Return one item per comment id."""


class _AIEngage(EngageEngine):
    def call(self, system: str, prompt: str) -> str:
        raise NotImplementedError

    def process(self, ctx, items, st):
        out = {c.id: rules_result(c, st) for c in items}  # fallback for anything the model gets wrong
        h = self.check()
        if not h.ok:
            return out, [f"{self.info.name} isn't set up ({h.message}); built-in rules sorted the comments."]
        last = getattr(ctx, "attempt", 1) >= get_settings().job_max_attempts
        notes: list[str] = []
        by_id = {c.id: c for c in items}
        for i in range(0, len(items), 25):
            chunk = items[i : i + 25]
            try:
                raw = self.call(SYSTEM, _prompt(chunk, st))
                data = json.loads(raw)
            except RetryableError:
                if not last:
                    raise
                notes.append(f"{self.info.name} was unavailable; built-in rules sorted some comments.")
                continue
            except EngineDeclined as e:
                notes.append(f"{self.info.name}: {e}; built-in rules sorted some comments.")
                continue
            except (ValueError, TypeError):
                notes.append(f"{self.info.name} returned an unreadable answer; built-in rules sorted some comments.")
                continue
            for it in data.get("items", []) if isinstance(data, dict) else []:
                c = by_id.get(str(it.get("id")))
                cat = it.get("category")
                if c is None or cat not in CATEGORIES:
                    continue
                reply = "" if cat == "spam" else clean_reply(str(it.get("reply", "")), c, st)
                if reply is None:
                    out[c.id] = CommentOut(cat, template_reply(cat, c.id, st)[: c.max_chars], "rules")
                    continue
                out[c.id] = CommentOut(cat, reply, self.info.id)
        return out, notes


class ClaudeEngageEngine(_AIEngage):
    info = EngineInfo(id="claude", stage=Stage.engage, name="Claude", kind="connector", description="Claude sorts comments and drafts replies in your voice, answering from what the clip says. Uses your Anthropic API key.")

    def check(self):
        return claude_health()

    def estimate(self, duration_s):
        return "about $0.01 per 25 comments (estimate)"

    def call(self, system, prompt):
        return claude_json(system, prompt, SCHEMA, max_tokens=8000)


class OllamaEngageEngine(_AIEngage):
    info = EngineInfo(id="ollama", stage=Stage.engage, name="Local model (Ollama)", kind="free", description="A model on your own machine sorts comments and drafts replies. Free and private.")

    def check(self):
        return ollama_health()

    def call(self, system, prompt):
        return ollama_json(system, prompt, SCHEMA)
