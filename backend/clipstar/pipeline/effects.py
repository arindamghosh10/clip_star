"""Light editing effects picked from the words: punch-in zooms on emphasis, and emojis next to the captions.

Both are deliberately sparse (a few per clip, never back to back): too many feel cheap and tire viewers.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ZOOM = 0.12  # 12% punch-in
RAMP = 0.15  # seconds to ease in and out
MAX_ZOOMS = 6
MAX_EMOJIS = 5
EMOJI_PX = 150

_NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty", "fifty", "hundred", "thousand", "million", "billion", "double", "half"}
EMPHASIS = _NUMBER_WORDS | {
    "never", "always", "biggest", "mistake", "mistakes", "secret", "free", "stop", "only", "every", "nobody", "everyone", "nothing",
    "huge", "worst", "best", "crazy", "insane", "must", "exactly", "truth", "wrong", "important", "warning", "seriously",
}

# word stem -> emoji. Kept to clear, neutral meanings.
EMOJI = {
    "money": "💰", "cash": "💰", "dollar": "💵", "pay": "💵", "paid": "💵", "salary": "💵", "rich": "🤑", "save": "💰", "saving": "💰", "bank": "🏦",
    "rent": "🏠", "house": "🏠", "home": "🏠", "lease": "📝", "contract": "📝", "sign": "✍️",
    "idea": "💡", "tip": "💡", "trick": "💡", "hack": "💡", "learn": "📚", "book": "📚",
    "mistake": "⚠️", "warning": "⚠️", "careful": "⚠️", "danger": "⚠️", "wrong": "❌", "never": "🚫", "stop": "🛑",
    "time": "⏰", "hour": "⏰", "minute": "⏱️", "fast": "⚡", "quick": "⚡",
    "grow": "📈", "growth": "📈", "up": "📈", "profit": "📈", "lose": "📉", "loss": "📉", "drop": "📉",
    "love": "❤️", "heart": "❤️", "happy": "😊", "funny": "😂", "laugh": "😂", "crazy": "🤯", "insane": "🤯", "mind": "🤯", "shock": "😱",
    "secret": "🤫", "think": "🤔", "why": "🤔", "question": "❓", "fire": "🔥", "hot": "🔥", "best": "🏆", "win": "🏆", "goal": "🎯", "target": "🎯",
    "work": "💼", "job": "💼", "business": "💼", "phone": "📱", "food": "🍽️", "eat": "🍽️", "coffee": "☕", "travel": "✈️", "car": "🚗",
    "health": "💪", "gym": "💪", "strong": "💪", "sleep": "😴", "music": "🎵", "camera": "🎥", "video": "🎥",
}


def _clean(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def pick_zooms(words: list[dict], duration: float, min_gap: float = 4.0) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for w in words:
        raw = w["word"].strip()
        c = _clean(raw)
        if not c:
            continue
        emphatic = c in EMPHASIS or any(ch.isdigit() for ch in c) or raw.endswith("!")
        if not emphatic:
            continue
        a = max(0.6, w["start"] - 0.05)  # not during the hook title's first moment
        b = min(duration - 0.2, max(w["end"] + 0.35, a + 0.7))
        if b - a < 0.5 or (out and a - out[-1][1] < min_gap):
            continue
        out.append((round(a, 3), round(b, 3)))
        if len(out) >= MAX_ZOOMS:
            break
    return out


def zoom_expr(zooms: list[tuple[float, float]]) -> str:
    """ffmpeg expression for the scale factor at time t: 1, easing up to 1+ZOOM inside each window."""
    if not zooms:
        return "1"
    parts = [f"max(0,min(1,(t-{a})/{RAMP}))*max(0,min(1,({b}-t)/{RAMP}))" for a, b in zooms]  # used inside '...' quotes
    return f"1+{ZOOM}*({'+'.join(parts)})"


def pick_emojis(words: list[dict], duration: float, min_gap: float = 3.0) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for w in words:
        c = _clean(w["word"])
        e = EMOJI.get(c) or EMOJI.get(_stem(c))
        if not e:
            continue
        a = max(0.3, w["start"])
        b = min(duration, a + 1.6)
        if b - a < 0.6 or (out and a - out[-1][1] < min_gap):
            continue
        if out and out[-1][2] == e:  # same emoji twice in a row looks repetitive
            continue
        out.append((round(a, 3), round(b, 3), e))
        if len(out) >= MAX_EMOJIS:
            break
    return out


@lru_cache
def _emoji_font(path: str):
    from PIL import ImageFont

    return ImageFont.truetype(path, 109)  # the colour bitmap font only comes at this size


def emoji_png(char: str, out: Path, font_path: str) -> bool:
    """Draw one colour emoji to a transparent PNG. False if the emoji font isn't installed."""
    from PIL import Image, ImageDraw

    if not Path(font_path).exists():
        return False
    font = _emoji_font(font_path)
    img = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((80, 80), char, font=font, embedded_color=True, anchor="mm")
    box = img.getbbox()
    if not box:
        return False
    img = img.crop(box)
    scale = EMOJI_PX / max(img.size)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    img.save(out)
    return True
