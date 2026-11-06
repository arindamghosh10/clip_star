"""Scene cuts and audio energy: the parts of 'Understand' that don't depend on the chosen engine."""

from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..media import run_ffmpeg

_PTS = re.compile(r"pts_time:([0-9.]+)")


def detect_scenes(video: Path, duration_s: float, on_progress, check_cancel) -> list[float]:
    """Return cut times in seconds (ffmpeg scene-change score above the threshold)."""
    thr = get_settings().scene_threshold
    err = run_ffmpeg(
        ["-i", str(video), "-an", "-vf", f"select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
        duration_s=duration_s,
        on_progress=on_progress,
        check_cancel=check_cancel,
        collect_stderr=True,
    )
    cuts = sorted({round(float(m.group(1)), 3) for m in _PTS.finditer(err)})
    return [c for c in cuts if 0 < c < duration_s]


def audio_energy(wav_path: Path, window_s: float = 1.0) -> dict:
    """Loudness per window (0..1) and the peak windows. Streams the file, so memory stays small."""
    with wave.open(str(wav_path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if width != 2:
            raise ValueError("expected 16-bit PCM audio")
        per = max(1, int(rate * window_s))
        rms: list[float] = []
        while True:
            frames = w.readframes(per)
            if not frames:
                break
            a = np.frombuffer(frames, dtype="<i2").astype(np.float32)
            if channels > 1:
                a = a.reshape(-1, channels).mean(axis=1)
            rms.append(float(np.sqrt(np.mean(a * a))) if a.size else 0.0)
    if not rms:
        return {"window_s": window_s, "values": [], "peaks": []}
    db = 20 * np.log10(np.maximum(np.array(rms), 1e-6) / 32768.0)
    floor, top = np.percentile(db, 5), np.percentile(db, 99.5)
    norm = np.clip((db - floor) / max(top - floor, 1e-6), 0, 1)
    mean, std = float(norm.mean()), float(norm.std())
    peaks = [i for i, v in enumerate(norm) if v > mean + 1.5 * std and v > 0.6]
    # keep only the highest point of each run of neighbouring peak windows
    merged: list[int] = []
    for i in peaks:
        if merged and i - merged[-1] <= 2:
            if norm[i] > norm[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)
    return {"window_s": window_s, "values": [round(float(v), 3) for v in norm], "peaks": [round(i * window_s, 2) for i in merged]}
