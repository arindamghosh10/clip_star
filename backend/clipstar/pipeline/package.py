"""Package: title, caption and hashtags for each platform, checked against that platform's rules.

Whatever an engine returns goes through `finalize_copy`, which normalises hashtags, enforces
length limits (trimming at a word boundary), replaces copy that mentions a banned topic, and
records preflight problems such as a clip that is too long for a platform.

The limits below are conservative defaults; platforms change them, so check before relying on
an exact number and adjust here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .moments import mentions_banned

PLATFORM_RULES: dict[str, dict] = {
    "youtube": {"label": "YouTube Shorts", "needs_title": True, "title_max": 100, "caption_max": 5000, "hashtags_max": 3, "max_duration": 180, "style": "Searchable title with the key words people would type. Caption: 1-2 sentences."},
    "instagram": {"label": "Instagram Reels", "needs_title": False, "title_max": 0, "caption_max": 2200, "hashtags_max": 5, "max_duration": 180, "style": "First line is a hook that makes people tap 'more'. Then 1-2 short lines and a call to action."},
    "tiktok": {"label": "TikTok", "needs_title": False, "title_max": 0, "caption_max": 2200, "hashtags_max": 5, "max_duration": 600, "style": "Short and casual, one or two lines."},
    "facebook": {"label": "Facebook", "needs_title": False, "title_max": 0, "caption_max": 2000, "hashtags_max": 3, "max_duration": 180, "style": "Conversational, 1-3 sentences, can ask a question to start comments."},
    "x": {"label": "X", "needs_title": False, "title_max": 0, "caption_max": 280, "hashtags_max": 2, "max_duration": 140, "style": "One punchy line. The whole post including hashtags must fit 280 characters."},
    "linkedin": {"label": "LinkedIn", "needs_title": False, "title_max": 0, "caption_max": 3000, "hashtags_max": 3, "max_duration": 600, "style": "Professional and useful: a clear takeaway in 2-4 short lines."},
    "threads": {"label": "Threads", "needs_title": False, "title_max": 0, "caption_max": 500, "hashtags_max": 1, "max_duration": 300, "style": "Casual, like a text to a friend. One topic tag at most."},
    "pinterest": {"label": "Pinterest", "needs_title": True, "title_max": 100, "caption_max": 500, "hashtags_max": 5, "max_duration": 300, "style": "Descriptive title and caption with keywords people search for."},
}
ALL_PLATFORMS = list(PLATFORM_RULES)

_STOP = set(
    """a an the and or but so if then than that this these those to of in on at for from with by as is are was were be been being it its
    i me my we our you your he she they them his her their what which who whom when where why how all any both each few more most other some
    such no nor not only own same too very can will just don should now do does did doing have has had having about into over after before
    again further once here there out up down off very really like get got going gonna want know think thing things said say lot also one
    two three four five dollars month year years people every single""".split()
)


@dataclass
class PackageSettings:
    platforms: list[str] = field(default_factory=lambda: list(ALL_PLATFORMS))
    hashtags: list[str] = field(default_factory=list)
    cta: str = "Follow for more."
    banned_topics: list[str] = field(default_factory=list)
    voice: str = ""
    niche: str = ""
    audience: str = ""
    auto_approve_score: int | None = None

    @classmethod
    def from_workspace(cls, s: dict | None) -> "PackageSettings":
        s = s or {}
        out = cls()
        if isinstance(s.get("platforms"), list):
            ps = [p for p in s["platforms"] if p in PLATFORM_RULES]
            out.platforms = ps or out.platforms
        if isinstance(s.get("hashtags"), list):
            out.hashtags = [h for h in (normalize_tag(str(x)) for x in s["hashtags"]) if h][:10]
        if isinstance(s.get("cta"), str):
            out.cta = s["cta"].strip()[:150]
        if isinstance(s.get("banned_topics"), list):
            out.banned_topics = [str(t).strip() for t in s["banned_topics"] if str(t).strip()]
        for k in ("voice", "niche", "audience"):
            if isinstance(s.get(k), str):
                setattr(out, k, s[k][:500])
        a = s.get("auto_approve_score")
        if isinstance(a, int) and 1 <= a <= 100:
            out.auto_approve_score = a
        return out


@dataclass
class ClipContext:
    title: str
    hook: str
    text: str  # what is said in the clip
    duration: float


def normalize_tag(tag: str) -> str:
    t = re.sub(r"[^\w]", "", tag.strip().lstrip("#"), flags=re.UNICODE)
    return t[:50]


def smart_trim(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def compose(copy: dict, platform: str) -> str:
    """The exact text that will be posted (caption + hashtags)."""
    tags = " ".join(f"#{h}" for h in copy.get("hashtags", []))
    cap = copy.get("caption", "").strip()
    return f"{cap}\n\n{tags}".strip() if tags else cap


def keywords(text: str, n: int = 3) -> list[str]:
    toks = [t for t in re.findall(r"[a-z][a-z']+", text.lower()) if len(t) >= 4 and t not in _STOP]
    return [w.replace("'", "") for w, _ in Counter(toks).most_common(n)]


def template_copy(ctx: ClipContext, platform: str, st: PackageSettings) -> dict:
    rules = PLATFORM_RULES[platform]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", ctx.text) if s.strip()]
    second = sentences[1] if len(sentences) > 1 else ""
    tags = st.hashtags + keywords(ctx.text)  # creator's own tags first, then topic words from the clip
    if platform in ("x", "threads"):
        caption = f"{ctx.title}"
    elif platform == "linkedin":
        caption = f"{ctx.title}\n\n{second}".strip()
    else:
        caption = f"{ctx.title}\n\n{second}\n\n{st.cta}".strip() if st.cta else f"{ctx.title}\n\n{second}".strip()
    return {"title": ctx.title if rules["needs_title"] else "", "caption": caption, "hashtags": tags}


def finalize_copy(raw: dict, ctx: ClipContext, st: PackageSettings) -> tuple[dict, dict, list[str]]:
    """Returns (copy per platform, preflight per platform, notes)."""
    copy: dict[str, dict] = {}
    pre: dict[str, dict] = {}
    notes: list[str] = []
    for p in st.platforms:
        rules = PLATFORM_RULES[p]
        c = raw.get(p) if isinstance(raw.get(p), dict) else None
        if c is None:
            c = template_copy(ctx, p, st)
        blob = f"{c.get('title', '')} {c.get('caption', '')} {' '.join(c.get('hashtags', []))}"
        topic = mentions_banned(blob, st.banned_topics)
        if topic:
            notes.append(f'{rules["label"]}: suggested copy mentioned "{topic}", so the template was used.')
            c = template_copy(ctx, p, st)
        tags: list[str] = []
        seen = set()
        for h in c.get("hashtags", []) or []:
            t = normalize_tag(str(h))
            if t and t.lower() not in seen and not mentions_banned(t, st.banned_topics):
                seen.add(t.lower())
                tags.append(t)
        tags = tags[: rules["hashtags_max"]]
        title = smart_trim(str(c.get("title") or ""), rules["title_max"]) if rules["needs_title"] else ""
        if rules["needs_title"] and not title:
            title = smart_trim(ctx.title, rules["title_max"])
        tag_len = (2 + sum(len(t) + 2 for t in tags)) if tags else 0
        caption = smart_trim(str(c.get("caption") or ""), rules["caption_max"] - tag_len)
        if not caption:
            caption = smart_trim(ctx.title, rules["caption_max"] - tag_len)
        out = {"title": title, "caption": caption, "hashtags": tags}
        problems = []
        if ctx.duration > rules["max_duration"]:
            problems.append(f"Clip is {ctx.duration:.0f}s; {rules['label']} allows up to {rules['max_duration']}s.")
        if len(compose(out, p)) > rules["caption_max"]:
            problems.append(f"Text is longer than {rules['caption_max']} characters.")
        copy[p] = out
        pre[p] = {"ok": not problems, "problems": problems, "chars": len(compose(out, p)), "limit": rules["caption_max"]}
    return copy, pre, notes


def check_copy(copy: dict, duration: float) -> dict:
    """Preflight for copy the user edited by hand (no trimming, just report)."""
    pre = {}
    for p, c in copy.items():
        rules = PLATFORM_RULES.get(p)
        if not rules or not isinstance(c, dict):
            continue
        problems = []
        if duration > rules["max_duration"]:
            problems.append(f"Clip is {duration:.0f}s; {rules['label']} allows up to {rules['max_duration']}s.")
        n = len(compose(c, p))
        if n > rules["caption_max"]:
            problems.append(f"Text is {n} characters; the limit is {rules['caption_max']}.")
        if rules["needs_title"] and not c.get("title"):
            problems.append("A title is required.")
        if rules["needs_title"] and len(c.get("title", "")) > rules["title_max"]:
            problems.append(f"Title is longer than {rules['title_max']} characters.")
        if len(c.get("hashtags", [])) > rules["hashtags_max"]:
            problems.append(f"More than {rules['hashtags_max']} hashtags.")
        pre[p] = {"ok": not problems, "problems": problems, "chars": n, "limit": rules["caption_max"]}
    return pre
