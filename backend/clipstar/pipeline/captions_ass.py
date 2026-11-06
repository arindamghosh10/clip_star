"""Burned-in captions as an ASS subtitle file: word-by-word highlight, plus a hook title at the top."""

from __future__ import annotations

from dataclasses import dataclass

W, H = 1080, 1920


@dataclass(frozen=True)
class CaptionStyle:
    id: str
    size: int
    uppercase: bool
    highlight: bool
    max_words: int
    max_chars: int
    margin_v: int  # distance from the bottom; leaves room for platform buttons and captions


STYLES = {
    "bold-pop": CaptionStyle("bold-pop", size=86, uppercase=True, highlight=True, max_words=3, max_chars=18, margin_v=560),
    "clean": CaptionStyle("clean", size=74, uppercase=False, highlight=False, max_words=5, max_chars=26, margin_v=520),
}

WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
HIGHLIGHT = "&H0000D7FF"  # warm yellow (ASS colours are &HAABBGGRR)


def _esc(text: str) -> str:
    # ASS treats { } as override blocks and \N as a line break; keep user text inert.
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _t(sec: float) -> str:
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def group_lines(words: list[dict], style: CaptionStyle, pause_s: float = 0.5) -> list[list[dict]]:
    lines: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        text = w["word"].strip()
        if not text:
            continue
        chars = sum(len(x["word"]) + 1 for x in cur) + len(text)
        if cur and (len(cur) >= style.max_words or chars > style.max_chars or w["start"] - cur[-1]["end"] > pause_s):
            lines.append(cur)
            cur = []
        cur.append(w)
        if text[-1] in ".!?":
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return lines


def build_ass(words: list[dict], duration: float, style_id: str, hook: str, font: str) -> str:
    style = STYLES.get(style_id, STYLES["bold-pop"])
    if style.highlight:  # thick outline, no box
        cap_style = f"Style: Cap,{font},{style.size},{WHITE},{WHITE},{BLACK},&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,80,80,{style.margin_v},1"
    else:  # white text on a translucent dark box: readable on any footage
        cap_style = f"Style: Cap,{font},{style.size},{WHITE},{WHITE},&H59000000,&H59000000,-1,0,0,0,100,100,0,0,3,16,0,2,90,90,{style.margin_v},1"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{cap_style}
Style: Hook,{font},74,{BLACK},{BLACK},{WHITE},{WHITE},-1,0,0,0,100,100,0,0,3,18,0,8,90,90,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    if hook.strip():
        events.append(f"Dialogue: 1,{_t(0)},{_t(min(3.0, duration))},Hook,,0,0,0,,{_esc(hook.strip().upper())}")

    def fmt(w: dict) -> str:
        t = _esc(w["word"].strip())
        return t.upper() if style.uppercase else t

    for line in group_lines(words, style):
        line_end = min(duration, line[-1]["end"] + 0.25)
        if style.highlight:
            for k, w in enumerate(line):
                start = w["start"]
                end = line[k + 1]["start"] if k + 1 < len(line) else line_end
                if end <= start:
                    continue
                parts = [(f"{{\\c{HIGHLIGHT}}}{fmt(x)}{{\\c{WHITE}}}" if i == k else fmt(x)) for i, x in enumerate(line)]
                events.append(f"Dialogue: 0,{_t(start)},{_t(min(end, duration))},Cap,,0,0,0,,{' '.join(parts)}")
        else:
            events.append(f"Dialogue: 0,{_t(line[0]['start'])},{_t(line_end)},Cap,,0,0,0,,{' '.join(fmt(x) for x in line)}")
    return header + "\n".join(events) + "\n"
