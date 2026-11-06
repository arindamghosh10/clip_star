"""Render one clip variant: 9:16 reframe, burned captions, hook title, loudness-normalised audio, cover image."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..errors import PermanentError
from ..media import probe, run_ffmpeg
from .captions_ass import build_ass
from .framing import Layout, video_filter

RENDER_VERSION = 3  # bump when the output changes, so old renders are redone


@dataclass
class RenderSpec:
    start: float
    end: float
    words: list[dict]  # relative to clip start
    hook: str
    caption_style: str
    layout: Layout

    def key(self) -> str:
        st = get_settings()
        blob = json.dumps(
            {
                "v": RENDER_VERSION,
                "s": round(self.start, 3),
                "e": round(self.end, 3),
                "w": self.words,
                "h": self.hook,
                "c": self.caption_style,
                "l": self.layout.as_dict(),
                "q": [st.render_preset, st.render_crf, st.caption_font],
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:24]


def render_clip(src: Path, src_w: int, src_h: int, has_audio: bool, spec: RenderSpec, out: Path, cover: Path, on_progress, check_cancel) -> dict:
    st = get_settings()
    dur = spec.end - spec.start
    workdir = Path(tempfile.mkdtemp(prefix="clipstar-render-"))
    try:
        ass = workdir / "captions.ass"
        ass.write_text(build_ass(spec.words, dur, spec.caption_style, spec.hook, st.caption_font), encoding="utf-8")
        graph = video_filter(spec.layout, src_w, src_h, str(ass))
        args = ["-ss", f"{spec.start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
        if not has_audio:
            # platforms expect an audio track; add silence
            args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        args += ["-filter_complex", graph, "-map", "[v]"]
        if has_audio:
            args += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"]
        else:
            args += ["-map", "1:a:0"]
        tmp_out = workdir / "out.mp4"
        args += [
            "-c:v", "libx264", "-preset", st.render_preset, "-crf", str(st.render_crf), "-profile:v", "high",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2",
            "-movflags", "+faststart", "-shortest", str(tmp_out),
        ]
        run_ffmpeg(args, duration_s=dur, on_progress=on_progress, check_cancel=check_cancel)

        info = probe(tmp_out)
        if (info.width, info.height) != (1080, 1920):
            raise PermanentError(f"rendered {info.width}x{info.height}", user_message="The rendered clip has the wrong size.")
        if abs(info.duration_s - dur) > 1.0:
            raise PermanentError(f"rendered {info.duration_s:.1f}s, wanted {dur:.1f}s", user_message="The rendered clip has the wrong length.")

        tmp_cover = workdir / "cover.jpg"
        run_ffmpeg(["-ss", f"{min(1.0, dur / 2):.2f}", "-i", str(tmp_out), "-frames:v", "1", "-q:v", "3", str(tmp_cover)], timeout_s=60)

        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_out), out)
        shutil.move(str(tmp_cover), cover)
        return {"duration_s": round(info.duration_s, 2), "size_bytes": out.stat().st_size}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
