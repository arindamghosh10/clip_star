"""Find moments: turn a transcript + audio energy + scene cuts into ranked, self-contained clip candidates.

Every engine (rules, Claude, local model) picks clips by *sentence ids*, never raw timestamps,
so a clip always starts and ends on a complete sentence. All results pass `finalize()`, which
enforces length limits, removes overlaps and banned topics, and clamps scores.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

# ---------- settings ----------


@dataclass
class MomentSettings:
    min_s: float = 15.0
    max_s: float = 60.0
    target_s: float = 40.0
    max_clips: int = 8
    min_score: int = 30
    banned_topics: list[str] = field(default_factory=list)
    niche: str = ""
    voice: str = ""
    audience: str = ""

    @classmethod
    def from_workspace(cls, settings: dict | None) -> "MomentSettings":
        s = settings or {}
        out = cls()
        for k in ("min_s", "max_s", "target_s"):
            if isinstance(s.get(f"clip_{k}"), (int, float)):
                setattr(out, k, float(s[f"clip_{k}"]))
        if isinstance(s.get("max_clips"), int):
            out.max_clips = max(1, min(30, s["max_clips"]))
        if isinstance(s.get("banned_topics"), list):
            out.banned_topics = [str(t).strip() for t in s["banned_topics"] if str(t).strip()]
        for k in ("niche", "voice", "audience"):
            if isinstance(s.get(k), str):
                setattr(out, k, s[k])
        # keep the limits sane whatever was saved
        out.min_s = max(5.0, min(out.min_s, 170.0))
        out.max_s = max(out.min_s + 5, min(out.max_s, 180.0))
        out.target_s = max(out.min_s, min(out.target_s, out.max_s))
        return out


# ---------- sentences ----------


@dataclass
class Sentence:
    id: int
    start: float
    end: float
    text: str
    words: list[dict]


_END = re.compile(r"[.!?…]['\")\]]*$")


def build_sentences(transcript: dict, max_sentence_s: float = 20.0, pause_s: float = 0.9) -> list[Sentence]:
    """Split the transcript into sentences using punctuation and long pauses."""
    out: list[Sentence] = []
    cur: list[dict] = []

    def flush():
        nonlocal cur
        if cur:
            text = " ".join(w["word"] for w in cur).strip()
            if text:
                out.append(Sentence(id=len(out), start=cur[0]["start"], end=cur[-1]["end"], text=text, words=cur))
        cur = []

    for seg in transcript.get("segments", []):
        words = seg.get("words") or []
        if not words:  # no word timings: the segment is the sentence
            flush()
            if seg.get("text", "").strip():
                cur = [{"start": seg["start"], "end": seg["end"], "word": seg["text"].strip()}]
                flush()
            continue
        for w in words:
            if cur and (w["start"] - cur[-1]["end"] > pause_s or w["end"] - cur[0]["start"] > max_sentence_s):
                flush()
            cur.append({"start": float(w["start"]), "end": float(w["end"]), "word": w["word"].strip()})
            if _END.search(w["word"].strip()):
                flush()
    flush()
    return out


# ---------- candidates ----------


@dataclass
class Candidate:
    start_id: int
    end_id: int
    start: float
    end: float
    title: str = ""
    hook: str = ""
    reason: str = ""
    score: int = 0
    heuristic: int = 0
    features: dict = field(default_factory=dict)
    engine: str = "rules"

    @property
    def duration(self) -> float:
        return self.end - self.start


_FILLER = {"and", "so", "but", "um", "uh", "like", "also", "or", "because", "then", "anyway", "yeah", "okay", "ok", "well"}
_STRONG = {
    "nobody", "never", "always", "secret", "mistake", "truth", "wrong", "worst", "best", "stop", "why", "how",
    "biggest", "everyone", "nothing", "only", "actually", "crazy", "shocking", "lost", "won", "free", "money",
    "dollars", "million", "billion", "warning", "important", "rule", "trick", "hack",
}
_NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "hundred", "thousand", "million", "billion", "forty", "fifty", "twenty", "thirty"}


# Housekeeping that never makes a good short: intros, outros, sponsor reads, calls to subscribe.
_HOUSEKEEPING = re.compile(
    r"\b(welcome (back )?to|thanks? (you )?for watching|see you (next|in the next)|let me know in the comments|"
    r"(like and )?subscribe|hit the bell|sponsor(ed)?|this video is brought to you|link in (the )?(bio|description)|"
    r"patreon|before we (get started|begin)|quick (thank you|shout ?out))\b",
    re.I,
)
_TRAILING_STOP = {"about", "the", "a", "an", "to", "of", "for", "and", "with", "in", "on", "at", "is", "are", "this", "that", "my", "your", "our", "it", "was", "but", "or", "so"}


def is_housekeeping(text: str) -> bool:
    return bool(_HOUSEKEEPING.search(text))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$%']+", text.lower())


def hook_strength(text: str) -> tuple[float, list[str]]:
    toks = _tokens(text)
    if not toks:
        return 0.0, []
    why = []
    s = 0.0
    if text.strip().endswith("?"):
        s += 0.35
        why.append("opens with a question")
    if any(t.isdigit() or t.startswith("$") or t in _NUMBER_WORDS for t in toks):
        s += 0.25
        why.append("opens with a number")
    strong = [t for t in toks if t in _STRONG]
    if strong:
        s += min(0.35, 0.15 * len(strong))
        why.append(f'strong opening word "{strong[0]}"')
    if "you" in toks or "your" in toks:
        s += 0.15
        why.append("speaks to the viewer")
    if len(toks) <= 12:
        s += 0.1
    if toks[0] in _FILLER:
        s -= 0.3
    return max(0.0, min(1.0, s)), why


class Signals:
    """Audio energy and scene cuts, ready for window queries."""

    def __init__(self, energy: dict | None, cuts: list[float] | None):
        e = energy or {}
        self.window = float(e.get("window_s") or 1.0)
        self.values = np.asarray(e.get("values") or [], dtype=np.float32)
        self.mean = float(self.values.mean()) if self.values.size else 0.0
        self.peaks = list(e.get("peaks") or [])
        self.cuts = sorted(cuts or [])

    def energy(self, a: float, b: float) -> float:
        if not self.values.size:
            return 0.0
        i, j = int(a / self.window), max(int(a / self.window) + 1, int(math.ceil(b / self.window)))
        seg = self.values[i:j]
        return float(seg.mean()) if seg.size else 0.0

    def peaks_in(self, a: float, b: float) -> list[float]:
        return [p for p in self.peaks if a <= p <= b]

    def cuts_in(self, a: float, b: float) -> int:
        return sum(1 for c in self.cuts if a < c < b)


def score_window(sents: list[Sentence], i: int, j: int, sig: Signals, st: MomentSettings) -> Candidate:
    a, b = sents[i].start, sents[j].end
    dur = b - a
    text = " ".join(s.text for s in sents[i : j + 1])
    hook, hook_why = hook_strength(sents[i].text)
    energy = sig.energy(a, b)
    rel_energy = 0.5 if sig.mean <= 0 else max(0.0, min(1.0, 0.5 + (energy - sig.mean) * 2))
    peaks = sig.peaks_in(a, b)
    complete = 1.0 if _END.search(sents[j].text) else 0.5
    length_fit = math.exp(-(((dur - st.target_s) / 15.0) ** 2))
    wps = len(_tokens(text)) / max(dur, 1e-6)
    density = 1.0 if 1.8 <= wps <= 3.8 else 0.5
    cuts = sig.cuts_in(a, b)
    visual = min(1.0, cuts / max(1.0, dur / 10))

    total = 0.32 * hook + 0.22 * rel_energy + 0.1 * min(1, len(peaks)) + 0.14 * complete + 0.12 * length_fit + 0.06 * density + 0.04 * visual
    chores = sum(1 for s in sents[i : j + 1] if is_housekeeping(s.text))
    if chores:
        total -= 0.25 + 0.1 * (chores - 1)  # intros, outros and ads drag a clip down hard
    score = int(round(100 * max(0.0, total)))

    why = hook_why[:2]
    if chores:
        why.append("includes intro/outro or sponsor talk")
    if peaks:
        why.append(f"high-energy moment at {_ts(peaks[0])}")
    if complete == 1.0:
        why.append("ends on a complete thought")
    why.append(f"{dur:.0f}s long")
    cand = Candidate(
        start_id=i,
        end_id=j,
        start=a,
        end=b,
        score=score,
        heuristic=score,
        reason=_sentence_case("; ".join(why)),
        features={"housekeeping": chores, "hook": round(hook, 2), "energy": round(rel_energy, 2), "peaks": len(peaks), "complete": complete, "length_fit": round(length_fit, 2), "words_per_s": round(wps, 2), "cuts": cuts},
    )
    cand.title = make_title(sents[i].text)
    cand.hook = make_hook(sents[i].text)
    return cand


def _ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _sentence_case(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def make_title(first_sentence: str, limit: int = 70) -> str:
    t = re.sub(r"\s+", " ", first_sentence).strip().rstrip(",;:")
    words = t.split()
    while words and words[0].lower().strip(",.") in _FILLER:
        words.pop(0)
    t = " ".join(words) or t
    if len(t) > limit:
        t = t[: limit - 1].rsplit(" ", 1)[0] + "…"
    return _sentence_case(t)


def make_hook(first_sentence: str, max_words: int = 5) -> str:
    words = [w.strip(",.!?;:\"'") for w in first_sentence.split()]
    words = [w for w in words if w]
    while words and words[0].lower() in _FILLER:
        words.pop(0)
    cut = words[:max_words]
    # don't end on a dangling word ("NOBODY TELLS YOU THIS ABOUT")
    while len(cut) > 2 and cut[-1].lower() in _TRAILING_STOP:
        cut.pop()
    return " ".join(cut).upper()


def rules_candidates(sents: list[Sentence], sig: Signals, st: MomentSettings, duration: float) -> list[Candidate]:
    """Score every sentence window that fits the length limits."""
    out: list[Candidate] = []
    n = len(sents)
    for i in range(n):
        if sents[i].text.split()[0].lower().strip(",.") in _FILLER and i + 1 < n:
            # still allowed, but rarely a good start; skip to keep the search small
            continue
        for j in range(i, n):
            dur = sents[j].end - sents[i].start
            if dur > st.max_s:
                break
            if dur >= st.min_s:
                out.append(score_window(sents, i, j, sig, st))
    if not out and n:
        # a very short video, or one long sentence: offer the best single window available
        best_j = max(range(n), key=lambda j: min(sents[j].end - sents[0].start, st.max_s))
        out.append(score_window(sents, 0, best_j, sig, st))
    return out


def energy_candidates(sig: Signals, st: MomentSettings, duration: float) -> list[Candidate]:
    """No speech at all (music, gameplay): build windows around the loudest moments, snapped to scene cuts."""
    out = []
    for p in sig.peaks or ([duration / 2] if duration >= st.min_s else []):
        a = max(0.0, p - st.target_s * 0.4)
        b = min(duration, a + st.target_s)
        a = max(0.0, b - st.target_s)
        before = [c for c in sig.cuts if a - 3 <= c <= a + 3]
        if before:
            a = before[-1]
        if b - a < st.min_s:
            continue
        energy = sig.energy(a, b)
        score = int(round(100 * (0.3 + 0.5 * min(1.0, energy / max(sig.mean, 1e-6) / 2))))
        out.append(
            Candidate(start_id=-1, end_id=-1, start=a, end=b, score=min(score, 90), heuristic=score, title=f"Moment at {_ts(p)}", hook="", reason=f"Loudest moment at {_ts(p)}; no speech detected", engine="energy")
        )
    return out


# ---------- shared validation for every engine ----------


def overlap(a: Candidate, b: Candidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / max(1e-6, min(a.duration, b.duration))


def mentions_banned(text: str, banned: list[str]) -> str | None:
    low = text.lower()
    for t in banned:
        if t and re.search(rf"\b{re.escape(t.lower())}\b", low):
            return t
    return None


def finalize(cands: list[Candidate], sents: list[Sentence], st: MomentSettings, duration: float) -> tuple[list[Candidate], list[str]]:
    """Clamp, drop invalid/banned/overlapping clips, keep the best `max_clips`. Returns (clips, notes)."""
    notes: list[str] = []
    valid = []
    for c in cands:
        c.score = int(max(0, min(100, c.score)))
        c.start = max(0.0, c.start)
        c.end = min(duration or c.end, c.end)
        if c.duration < st.min_s * 0.8 or c.duration > st.max_s * 1.15:
            continue
        if c.start_id >= 0:
            text = " ".join(s.text for s in sents[c.start_id : c.end_id + 1])
            topic = mentions_banned(text, st.banned_topics)
            if topic:
                notes.append(f'Skipped a moment at {_ts(c.start)} because it mentions "{topic}".')
                continue
        c.title = (c.title or "Untitled moment").strip()[:300]
        c.hook = (c.hook or "").strip()[:200]
        c.reason = (c.reason or "").strip()[:1000]
        valid.append(c)
    valid.sort(key=lambda c: (-c.score, c.start))
    chosen: list[Candidate] = []
    for c in valid:
        if all(overlap(c, k) < 0.25 for k in chosen):
            chosen.append(c)
        if len(chosen) >= st.max_clips:
            break
    keep = [c for c in chosen if c.score >= st.min_score] or chosen[:1]
    return sorted(keep, key=lambda c: -c.score), notes


def clip_words(sents: list[Sentence], c: Candidate) -> list[dict]:
    """Word timings for the clip, relative to the clip start (used for captions)."""
    if c.start_id < 0:
        return []
    out = []
    for s in sents[c.start_id : c.end_id + 1]:
        for w in s.words:
            out.append({"start": round(w["start"] - c.start, 3), "end": round(w["end"] - c.start, 3), "word": w["word"]})
    return out
