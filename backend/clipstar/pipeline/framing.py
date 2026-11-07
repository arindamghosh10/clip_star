"""Decide how to turn a landscape clip into 9:16.

- crop:  faces are present -> crop a 9:16 window centred on the main speaker, one position per scene
         (moving only at scene cuts looks deliberate; frame-by-frame tracking looks jittery).
- fit:   no faces (screen recordings, gameplay, slides) -> the whole frame, centred over a blurred copy.
- scale: the source is already vertical.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FaceDetector = Callable[[np.ndarray], list[tuple[int, int, int, int]]]  # frame -> [(x, y, w, h)]


@dataclass
class Layout:
    mode: str  # crop | fit | scale
    segments: list[tuple[float, float, float]]  # (start_s, end_s, centre_x 0..1), relative to the clip
    face_ratio: float = 0.0

    def as_dict(self) -> dict:
        return {"mode": self.mode, "segments": [list(s) for s in self.segments], "face_ratio": round(self.face_ratio, 2)}


_cascade = None


def haar_detector(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    import cv2

    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h = gray.shape[0]
    faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, h // 14), max(24, h // 14)))
    return [tuple(int(v) for v in f) for f in faces]


def plan_layout(video: Path, start: float, end: float, cuts: list[float], src_w: int, src_h: int, detector: FaceDetector | None = None, fps: float = 2.0) -> Layout:
    dur = end - start
    if src_h >= src_w:
        return Layout("scale", [(0.0, dur, 0.5)])
    import cv2

    detector = detector or haar_detector
    cap = cv2.VideoCapture(str(video))
    samples: list[tuple[float, float | None]] = []  # (t relative, centre x or None)
    try:
        n = max(1, int(dur * fps))
        for k in range(n):
            t = start + (k + 0.5) / fps
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            faces = detector(frame)
            if faces:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # largest face = main speaker
                samples.append((t - start, (x + w / 2) / frame.shape[1]))
            else:
                samples.append((t - start, None))
    finally:
        cap.release()

    found = [s for s in samples if s[1] is not None]
    ratio = len(found) / max(1, len(samples))
    if ratio < 0.4:
        return Layout("fit", [(0.0, dur, 0.5)], ratio)

    bounds = [0.0] + [c - start for c in cuts if start + 0.5 < c < end - 0.5] + [dur]
    segs: list[tuple[float, float, float]] = []
    last = float(np.median([s[1] for s in found]))
    for a, b in zip(bounds, bounds[1:]):
        xs = [x for t, x in found if a <= t < b]
        cx = float(np.median(xs)) if xs else last
        last = cx
        segs.append((round(a, 3), round(b, 3), round(cx, 4)))
    return Layout("crop", segs, ratio)


def video_filter(layout: Layout, src_w: int, src_h: int, ass_path: str | None, zoom: str | None = None, overlays: list[tuple[int, int, float, float]] | None = None) -> str:
    """ffmpeg filter graph from input [0:v] to output [v] at 1080x1920.

    zoom: an expression in t for the punch-in factor (1 = none), applied under the captions.
    overlays: (input index, y, start, end) images centred horizontally, e.g. emojis above the captions.
    """
    if layout.mode == "crop":
        cw = min(src_w, int(round(src_h * 9 / 16 / 2)) * 2)
        xs = [max(0, min(src_w - cw, int(cx * src_w - cw / 2))) for _, _, cx in layout.segments]
        expr = str(xs[-1])
        for (a, b, _), x in reversed(list(zip(layout.segments[:-1], xs[:-1]))):
            expr = f"if(lt(t\\,{b:.3f})\\,{x}\\,{expr})"
        chain = f"[0:v]crop={cw}:{src_h}:{expr}:0,scale=1080:1920:flags=lanczos,setsar=1"
    elif layout.mode == "fit":
        chain = (
            "[0:v]split=2[bgsrc][fgsrc];"
            "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,eq=brightness=-0.08[bg];"
            "[fgsrc]scale=1080:-2:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    else:
        chain = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if zoom and zoom != "1":
        # per-frame scale up, then crop back to the centre: a smooth punch-in
        chain += f",scale=w='trunc(1080*({zoom})/2)*2':h=-2:eval=frame:flags=bicubic,crop=1080:1920,setsar=1"
    if overlays:
        chain += "[base0]"
        for k, (idx, y, a, b) in enumerate(overlays):
            nxt = f"[base{k + 1}]"
            chain += f";[base{k}][{idx}:v]overlay=x=(W-w)/2:y={y}:enable='between(t,{a},{b})'{nxt}"
        chain += f";[base{len(overlays)}]null"
    if ass_path:
        chain += f",ass=filename='{_filter_path(ass_path)}'"
    return chain + ",fps=30,format=yuv420p[v]"


def _filter_path(p: str) -> str:
    # escape for an ffmpeg filter argument inside single quotes
    return p.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
