"""FFmpeg / FFprobe helpers with progress, cancellation, timeouts and clear errors."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings
from .errors import Cancelled, PermanentError, RetryableError


@dataclass
class ProbeResult:
    duration_s: float
    width: int
    height: int
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: str | None
    size_bytes: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def tools_available() -> dict[str, bool]:
    st = get_settings()
    return {"ffmpeg": shutil.which(st.ffmpeg_bin) is not None, "ffprobe": shutil.which(st.ffprobe_bin) is not None}


def _fps(rate: str | None) -> float:
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    if "/" in rate:
        n, d = rate.split("/", 1)
        return float(n) / float(d) if float(d) else 0.0
    return float(rate)


def probe(path: Path) -> ProbeResult:
    st = get_settings()
    try:
        out = subprocess.run(
            [st.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:
        raise PermanentError("ffprobe is not installed.", user_message="FFmpeg is not installed on the worker machine.") from e
    except subprocess.TimeoutExpired as e:
        raise RetryableError("ffprobe timed out") from e
    if out.returncode != 0:
        raise PermanentError(f"ffprobe failed: {out.stderr.strip()[-500:]}", user_message="This file couldn't be read as a video. It may be damaged or not a video.")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video" and not x.get("disposition", {}).get("attached_pic")), None)
    a = next((x for x in streams if x.get("codec_type") == "audio"), None)
    if v is None:
        raise PermanentError("no video stream", user_message="This file has no video track.")
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    if duration <= 0:
        raise PermanentError("zero duration", user_message="This video has no length. It may be damaged.")
    return ProbeResult(
        duration_s=duration,
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        fps=round(_fps(v.get("avg_frame_rate") or v.get("r_frame_rate")), 3),
        video_codec=v.get("codec_name", ""),
        has_audio=a is not None,
        audio_codec=a.get("codec_name") if a else None,
        size_bytes=int(data.get("format", {}).get("size") or path.stat().st_size),
    )


_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def run_ffmpeg(
    args: list[str],
    *,
    duration_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    check_cancel: Callable[[], None] | None = None,
    timeout_s: float | None = None,
    collect_stderr: bool = False,
) -> str:
    """Run ffmpeg. Reports progress (0-100) when duration is known. Kills ffmpeg on cancel or timeout.
    Returns stderr text if collect_stderr, else the last lines (for error messages)."""
    st = get_settings()
    cmd = [st.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    if timeout_s is None:
        timeout_s = 600 + 4 * (duration_s or 600)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    except FileNotFoundError as e:
        raise PermanentError("ffmpeg not installed", user_message="FFmpeg is not installed on the worker machine.") from e

    tail: deque[str] = deque(maxlen=40)
    full: list[str] = []

    def read_err():
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line.rstrip())
            if collect_stderr:
                full.append(line)

    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    # Watchdog: kills ffmpeg even if it hangs without printing anything.
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout_s, _kill)
    timer.daemon = True
    timer.start()
    start = time.monotonic()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if check_cancel:
                check_cancel()
            if time.monotonic() - start > timeout_s:
                raise RetryableError("ffmpeg took too long", user_message="Video processing timed out.")
            m = _TIME_RE.match(line.strip())
            if m and duration_s and on_progress:
                # out_time_us and out_time_ms are both microseconds in ffmpeg's progress output
                on_progress(min(100.0, int(m.group(1)) / 1_000_000 / duration_s * 100))
        rc = proc.wait(timeout=max(1.0, timeout_s - (time.monotonic() - start)))
    except (Cancelled, RetryableError, subprocess.TimeoutExpired) as e:
        proc.kill()
        proc.wait()
        if isinstance(e, subprocess.TimeoutExpired):
            raise RetryableError("ffmpeg took too long", user_message="Video processing timed out.") from e
        raise
    finally:
        timer.cancel()
        t.join(timeout=5)
    if timed_out.is_set():
        raise RetryableError("ffmpeg took too long", user_message="Video processing timed out.")
    if rc != 0:
        msg = "\n".join(list(tail)[-8:])
        raise PermanentError(f"ffmpeg exited {rc}: {msg}", user_message=f"Video processing failed: {msg.splitlines()[-1] if msg else 'unknown error'}")
    return "".join(full) if collect_stderr else "\n".join(tail)
