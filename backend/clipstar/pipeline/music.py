"""Background music: the creator's own tracks, mixed quietly under speech.

Uploads are converted to one format (AAC, 48 kHz stereo) so rendering never trips over odd files.
In a clip the music fades in and out, and ducks (gets quieter) automatically whenever someone speaks.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..config import get_settings
from ..errors import PermanentError
from ..media import run_ffmpeg

ALLOWED = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".flac", ".opus")
MAX_BYTES = 50 * 1024 * 1024
DEFAULT_VOLUME = 0.18


def audio_duration(path: Path) -> float:
    st = get_settings()
    out = subprocess.run([st.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout or "{}")
    if out.returncode != 0 or not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise PermanentError("not audio", user_message="That file isn't audio clip_star can read (use MP3, M4A, WAV, OGG or FLAC).")
    return float(data.get("format", {}).get("duration") or 0)


def import_track(src: Path, dest: Path) -> float:
    """Convert an upload to AAC; returns its length in seconds."""
    audio_duration(src)  # refuse non-audio before spending time converting
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(src), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-y", str(dest)], timeout_s=600)
    d = audio_duration(dest)
    if d < 3:
        raise PermanentError("too short", user_message="The track is shorter than 3 seconds.")
    return d


def audio_graph(has_voice: bool, music_input: int, volume: float, dur: float) -> str:
    """filter_complex part producing [a]: loudness-normalised voice with music ducked underneath."""
    vol = max(0.0, min(1.0, volume))
    fade_out = max(0.0, dur - 1.2)
    music = f"[{music_input}:a]aresample=48000,volume={vol if has_voice else min(1.0, vol * 2.5):.3f},afade=t=in:d=0.6,afade=t=out:st={fade_out:.2f}:d=1.2"
    if not has_voice:
        return f"{music},alimiter=limit=0.95[a]"
    return (
        "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asplit=2[voice][sc];"
        f"{music}[bgm];"
        "[bgm][sc]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[duck];"
        "[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
    )
