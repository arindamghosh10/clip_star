"""Editing a transcript by hand: new text per segment, word timings re-aligned so captions stay in sync."""

from __future__ import annotations


def realign(seg: dict, text: str) -> list[dict]:
    """Words for edited segment text. Same word count: keep each word's timing. Otherwise spread the
    segment's time over the new words in proportion to their length (good enough for captions)."""
    tokens = text.split()
    old = seg.get("words") or []
    if old and len(old) == len(tokens):
        return [{**w, "word": t} for w, t in zip(old, tokens)]
    start = float(seg.get("start", old[0]["start"] if old else 0.0))
    end = float(seg.get("end", old[-1]["end"] if old else start))
    if not tokens or end <= start:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    out, t = [], start
    for tok, w in zip(tokens, weights):
        d = (end - start) * w / total
        out.append({"start": round(t, 3), "end": round(t + d, 3), "word": tok, "estimated": True})
        t += d
    return out


def apply_edits(tr: dict, edits: list[dict]) -> list[tuple[float, float]]:
    """Apply [{"index": i, "text": "..."}]; returns the time ranges that changed. Raises ValueError on bad input."""
    segs = tr.get("segments", [])
    changed = []
    for e in edits:
        i = e["index"]
        if not 0 <= i < len(segs):
            raise ValueError(f"There's no segment {i + 1}.")
        text = " ".join(str(e["text"]).split())
        if not text:
            raise ValueError(f"Segment {i + 1} can't be empty. Remove the words you don't want instead of the whole line.")
        seg = segs[i]
        if text == " ".join(str(seg.get("text", "")).split()):
            continue
        seg["words"] = realign(seg, text)
        seg["text"] = text
        seg["edited"] = True
        changed.append((float(seg.get("start", 0.0)), float(seg.get("end", 0.0))))
    return changed
