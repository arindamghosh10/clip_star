"""Custom cover images: uploaded by the user or picked from a frame of the clip. Re-renders never overwrite them."""

from __future__ import annotations

import uuid

import cv2
import numpy as np

from ..media import run_ffmpeg
from ..storage import get_storage

W, H = 1080, 1920
MAX_BYTES = 10 * 1024 * 1024


def cover_rel(c, variant: str) -> str | None:
    """The cover to use for a variant: the custom one if set, else the auto one from rendering."""
    meta = c.meta or {}
    custom = (meta.get("custom_covers") or {}).get(variant)
    if custom and get_storage().exists(custom):
        return custom
    r = (meta.get("renders") or {}).get(variant) or {}
    return r.get("cover")


def fit_9x16(img: np.ndarray) -> np.ndarray:
    """Scale to fill 1080x1920 and centre-crop the overflow."""
    h, w = img.shape[:2]
    scale = max(W / w, H / h)
    nw, nh = max(W, round(w * scale)), max(H, round(h * scale))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    x, y = (nw - W) // 2, (nh - H) // 2
    return img[y : y + H, x : x + W]


def save_cover(video_id, clip_id, variant: str, data: bytes) -> str:
    """Decode any common image (JPEG, PNG, WebP), fit it to 9:16 and store it. Raises ValueError for bad input."""
    if len(data) > MAX_BYTES:
        raise ValueError("The image is larger than 10 MB.")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("That file isn't an image clip_star can read (use JPEG, PNG or WebP).")
    if min(img.shape[:2]) < 200:
        raise ValueError("The image is too small; use at least 720 pixels wide.")
    ok, buf = cv2.imencode(".jpg", fit_9x16(img), [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("Couldn't save the image.")
    st = get_storage()
    rel = f"{st.video_dir(video_id)}/clips/{clip_id}/{variant}-cover-{uuid.uuid4().hex[:8]}.jpg"
    tmp = st.tmp_path_for(rel)
    try:
        tmp.write_bytes(buf.tobytes())
        st.commit_tmp(tmp, rel)
    finally:
        if tmp.exists():
            tmp.unlink()
    return rel


def frame_cover(video_id, clip_id, variant: str, rendered_rel: str, at_s: float) -> str:
    """Take a still from the rendered clip (so captions and framing match what viewers see)."""
    st = get_storage()
    rel = f"{st.video_dir(video_id)}/clips/{clip_id}/{variant}-cover-{uuid.uuid4().hex[:8]}.jpg"
    tmp = st.tmp_path_for(rel)
    try:
        run_ffmpeg(["-ss", f"{max(0.0, at_s):.2f}", "-i", str(st.abs(rendered_rel)), "-frames:v", "1", "-q:v", "2", "-y", str(tmp)], timeout_s=60)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise ValueError("Couldn't take a frame at that time.")
        st.commit_tmp(tmp, rel)
    finally:
        if tmp.exists():
            tmp.unlink()
    return rel
