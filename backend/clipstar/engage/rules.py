"""Free, rule-based comment sorting and reply templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(com|net|io|xyz|ru|top|link)\b", re.I)
_SPAM = re.compile(
    r"\b(dm me|check (out )?my (page|profile|bio)|link in (my )?bio|follow (me|back)|f4f|sub4sub|crypto|forex|bitcoin|10x|"
    r"giveaway|onlyfans|whatsapp me|telegram|earn \$?\d+|make money (fast|online)|free (followers|likes))\b",
    re.I,
)
_LEAD = re.compile(r"\b(collab(oration)?|sponsor(ship)?|partner(ship)?|business (inquiry|enquiry|email)|work with you|your rates?|brand deal|reach (out to )?you|contact you|hire you|email you|podcast guest|on our podcast)\b", re.I)
_CRITICAL = re.compile(r"\b(wrong|false|misleading|scam|clickbait|terrible|worst|hate|disagree|not true|liar|stupid|useless|bad advice|unsubscrib\w*)\b", re.I)
_PRAISE = re.compile(r"\b(thank(s| you)|love (this|it|your)|great|amazing|awesome|helpful|so good|well said|legend|brilliant|useful|saved me)\b|[❤️🔥🙏👏💯😍]", re.I)
_QUESTION = re.compile(r"\?|^\s*(how|what|why|when|where|which|who|can|could|does|do|is|are|should|would|will)\b", re.I)

CATEGORIES = ("question", "lead", "praise", "critical", "spam", "other")


def classify(text: str) -> str:
    t = text.strip()
    if not t:
        return "other"
    if _SPAM.search(t) or (_URL.search(t) and len(t) < 160):
        return "spam"
    if _LEAD.search(t):
        return "lead"
    if _CRITICAL.search(t):
        return "critical"
    if _QUESTION.search(t):
        return "question"
    if _PRAISE.search(t):
        return "praise"
    return "other"


@dataclass
class EngageSettings:
    voice: str = ""
    niche: str = ""
    banned_topics: list[str] = field(default_factory=list)
    lead_reply: str = "Thanks for reaching out! The best way to contact me is the link in my bio."
    auto_reply_categories: list[str] = field(default_factory=list)
    auto_hide_spam: bool = False
    replies_per_hour: int = 20
    sync_minutes: int = 15

    @classmethod
    def from_workspace(cls, s: dict | None) -> "EngageSettings":
        s = s or {}
        out = cls()
        for k in ("voice", "niche"):
            if isinstance(s.get(k), str):
                setattr(out, k, s[k][:500])
        if isinstance(s.get("banned_topics"), list):
            out.banned_topics = [str(x).strip() for x in s["banned_topics"] if str(x).strip()]
        if isinstance(s.get("lead_reply"), str) and s["lead_reply"].strip():
            out.lead_reply = s["lead_reply"].strip()[:500]
        if isinstance(s.get("auto_reply_categories"), list):
            # only low-risk categories may ever be sent without a human
            out.auto_reply_categories = [c for c in s["auto_reply_categories"] if c in ("praise", "lead")]
        out.auto_hide_spam = bool(s.get("auto_hide_spam", False))
        if isinstance(s.get("replies_per_hour"), int):
            out.replies_per_hour = max(1, min(200, s["replies_per_hour"]))
        if isinstance(s.get("comment_sync_minutes"), int):
            out.sync_minutes = max(5, min(1440, s["comment_sync_minutes"]))
        return out


_THANKS = ["Thank you so much! 🙏", "Really glad it helped!", "Thanks for watching!", "Appreciate you! 🙌", "So glad this was useful!"]


def template_reply(category: str, comment_id: str, st: EngageSettings) -> str:
    if category == "praise":
        return _THANKS[sum(map(ord, comment_id)) % len(_THANKS)]  # stable but varied
    if category == "lead":
        return st.lead_reply
    return ""  # questions and criticism need a real answer; spam gets none
