"""Render one clip variant: 9:16 reframe, burned captions, hook title, loudness-normalised audio, cover image."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings
from ..errors import PermanentError
from ..media import probe, run_ffmpeg
from .captions_ass import STYLES, build_ass
from .effects import emoji_png, zoom_expr
from .music import audio_graph
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
    zooms: list = field(default_factory=list)  # [(start, end)] punch-ins
    emojis: list = field(default_factory=list)  # [(start, end, emoji)]
    music: dict | None = None  # {"id", "path" (absolute), "volume", "offset"}
    broll: list = field(default_factory=list)  # [{"start", "end", "path", "id", ...}] full-screen cutaways
    voice: str | None = None  # dubbed audio replacing the clip's own (absolute path)

    def key(self) -> str:
        st = get_settings()
        extra = {}
        if self.zooms:
            extra["z"] = self.zooms
        if self.emojis:
            extra["m"] = self.emojis
        if self.voice:
            extra["vo"] = Path(self.voice).name
        if self.broll:
            extra["br"] = [[c["id"], c["start"], c["end"]] for c in self.broll]
        if self.music:
            extra["bg"] = [self.music["id"], round(self.music["volume"], 3), round(self.music.get("offset", 0), 2)]
        blob = json.dumps(
            {
                **extra,
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
        args = ["-ss", f"{spec.start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
        next_input = 1
        if not has_audio:
            # platforms expect an audio track; add silence
            args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            next_input += 1
        overlays = []
        margin = STYLES.get(spec.caption_style, STYLES["bold-pop"]).margin_v
        for k, (a, b, char) in enumerate(spec.emojis):
            png = workdir / f"emoji{k}.png"
            if emoji_png(char, png, st.emoji_font):
                args += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
                overlays.append((next_input, 1920 - margin - 330, a, b))
                next_input += 1
        cutaways = []
        for c in spec.broll:
            if Path(c["path"]).exists():
                args += ["-t", f"{c['end'] - c['start'] + 0.5:.2f}", "-i", c["path"]]
                cutaways.append((next_input, c["start"], c["end"]))
                next_input += 1
        voice_input = 0 if has_audio else None
        if spec.voice and Path(spec.voice).exists():
            args += ["-i", spec.voice]
            voice_input = next_input
            next_input += 1
        music_input = None
        if spec.music and Path(spec.music["path"]).exists():
            # loop the track if it's shorter than the clip
            args += ["-stream_loop", "-1", "-ss", f"{spec.music.get('offset', 0):.2f}", "-t", f"{dur:.3f}", "-i", spec.music["path"]]
            music_input = next_input
            next_input += 1
        graph = video_filter(spec.layout, src_w, src_h, str(ass), zoom_expr(spec.zooms), overlays, cutaways)
        if music_input is not None:
            graph += ";" + audio_graph(voice_input is not None, music_input, spec.music["volume"], dur, voice_input or 0)
            args += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
        else:
            args += ["-filter_complex", graph, "-map", "[v]"]
            if voice_input is not None:
                args += ["-map", f"{voice_input}:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,apad"]
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
