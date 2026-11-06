"""The video pipeline. Each stage is a durable job; finishing one enqueues the next in the same transaction.

Stages that are not built yet are simply not in PIPELINE; a video that finishes the
implemented stages becomes `ready` and later phases extend the list.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import session_scope
from ..engines.captions import CaptionsFileEngine
from ..engines.registry import ENGINES, chosen_engine_id
from ..errors import PermanentError
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..media import probe, run_ffmpeg
from ..models import Asset, Job, Stage, Video, VideoStatus
from ..storage import get_storage
from .analysis import audio_energy, detect_scenes

PIPELINE: list[Stage] = [Stage.ingest, Stage.understand]
JOB_KIND = "pipeline.stage"


# ---------- helpers ----------


def dedupe_key(video_id: uuid.UUID, stage: Stage) -> str:
    return f"video:{video_id}:{stage.value}"


def enqueue_stage(s: Session, video: Video, stage: Stage) -> Job:
    return queue.enqueue(s, JOB_KIND, {"stage": stage.value}, video_id=video.id, dedupe_key=dedupe_key(video.id, stage))


def start_pipeline(s: Session, video: Video) -> Job:
    video.status = VideoStatus.queued
    video.stage = PIPELINE[0]
    video.error = None
    return enqueue_stage(s, video, PIPELINE[0])


def _asset(s: Session, video_id: uuid.UUID, kind: str) -> Asset | None:
    return s.scalar(select(Asset).where(Asset.video_id == video_id, Asset.kind == kind))


def _asset_dict(kind: str, path: str, size: int, meta: dict | None = None) -> dict:
    return {"kind": kind, "path": path, "size_bytes": size, "meta": meta or {}}


def _load(video_id: uuid.UUID) -> tuple[Video, dict[str, Asset]]:
    with session_scope() as s:
        v = s.get(Video, video_id)
        if v is None:
            raise PermanentError("video deleted", user_message="This video was deleted.")
        if v.status == VideoStatus.cancelled:
            raise PermanentError("video cancelled", user_message="Processing was cancelled.")
        assets = {a.kind: a for a in s.scalars(select(Asset).where(Asset.video_id == video_id))}
        return v, assets


def _mark_running(video_id: uuid.UUID, stage: Stage) -> None:
    with session_scope() as s:
        v = s.get(Video, video_id, with_for_update=True)
        if v and v.status != VideoStatus.cancelled:
            v.status = VideoStatus.processing
            v.stage = stage
            v.error = None


# ---------- stage: ingest ----------


def run_ingest(ctx: JobContext, video: Video, assets: dict[str, Asset]) -> dict:
    st = get_storage()
    master = assets.get("master")
    if master is None or not st.exists(master.path):
        raise PermanentError("master missing", user_message="The uploaded file is missing. Please upload it again.")
    src = st.abs(master.path)
    info = probe(src)
    ctx.progress(3, f"{info.width}x{info.height}, {info.duration_s:.0f}s, audio: {'yes' if info.has_audio else 'no'}")

    from ..config import get_settings

    h = get_settings().proxy_height
    proxy_rel = st.rel(video.id, "proxy.mp4")
    tmp = st.tmp_path_for(proxy_rel)
    try:
        args = ["-i", str(src), "-map", "0:v:0", "-vf", f"scale=-2:'min({h},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]
        if info.has_audio:
            args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k"]
        args += ["-movflags", "+faststart", str(tmp)]
        run_ffmpeg(args, duration_s=info.duration_s, on_progress=lambda p: ctx.progress(3 + p * 0.77), check_cancel=ctx.check)
        proxy_size = st.commit_tmp(tmp, proxy_rel)
    finally:
        if tmp.exists():
            tmp.unlink()
    out = [_asset_dict("proxy", proxy_rel, proxy_size)]

    if info.has_audio:
        audio_rel = st.rel(video.id, "audio.wav")
        tmp = st.tmp_path_for(audio_rel)
        try:
            run_ffmpeg(
                ["-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)],
                duration_s=info.duration_s,
                on_progress=lambda p: ctx.progress(80 + p * 0.2),
                check_cancel=ctx.check,
            )
            out.append(_asset_dict("audio", audio_rel, st.commit_tmp(tmp, audio_rel)))
        finally:
            if tmp.exists():
                tmp.unlink()
    return {"assets": out, "video": {"duration_s": info.duration_s, "meta": {"probe": info.as_dict()}}}


# ---------- stage: understand ----------


def run_understand(ctx: JobContext, video: Video, assets: dict[str, Asset]) -> dict:
    st = get_storage()
    duration = video.duration_s or 0.0
    proxy = assets.get("proxy")
    if proxy is None or not st.exists(proxy.path):
        raise PermanentError("proxy missing", user_message="The processed copy is missing. Retry the Ingest step.")
    audio = assets.get("audio")
    captions = assets.get("captions")
    notes: list[str] = []

    # 1. transcript (0-70%)
    if captions and st.exists(captions.path):
        engine_id = CaptionsFileEngine.info.id
        transcript = CaptionsFileEngine().from_file(st.abs(captions.path), duration)
        notes.append("Used the captions file uploaded with the video.")
    elif audio and st.exists(audio.path):
        with session_scope() as s:
            engine_id = chosen_engine_id(s, video.workspace_id, Stage.understand) or "faster-whisper"
        engine = ENGINES.get(engine_id)
        if engine is None or not hasattr(engine, "transcribe"):
            raise PermanentError(f"engine {engine_id} unavailable", user_message=f"The transcription engine '{engine_id}' can't transcribe audio. Pick another in Engines & connectors.")
        health = engine.check()
        if not health.ok:
            raise PermanentError(health.message, user_message=f"{engine.info.name}: {health.message}")
        ctx.progress(1, f"Transcribing with {engine.info.name}")
        transcript = engine.transcribe(ctx, st.abs(audio.path), duration, lambda p: ctx.progress(1 + p * 0.69))
    else:
        from ..engines.base import Transcript

        engine_id = "none"
        transcript = Transcript(engine="none", duration=duration)
        notes.append("The video has no audio and no captions file, so there is no transcript.")
    tr_rel = st.rel(video.id, "transcript.json")
    tr_size = st.write_json(tr_rel, transcript.model_dump())
    ctx.progress(70, f"Transcript: {transcript.word_count} words")

    # 2. scenes (70-90%)
    scenes = detect_scenes(st.abs(proxy.path), duration, lambda p: ctx.progress(70 + p * 0.2), ctx.check)
    sc_rel = st.rel(video.id, "scenes.json")
    sc_size = st.write_json(sc_rel, {"cuts": scenes})

    # 3. audio energy (90-100%)
    if audio and st.exists(audio.path):
        energy = audio_energy(st.abs(audio.path))
    else:
        energy = {"window_s": 1.0, "values": [], "peaks": []}
    en_rel = st.rel(video.id, "energy.json")
    en_size = st.write_json(en_rel, energy)
    ctx.progress(100)

    summary = {
        "transcript_engine": engine_id,
        "language": transcript.language,
        "words": transcript.word_count,
        "segments": len(transcript.segments),
        "words_estimated": transcript.words_estimated,
        "scenes": len(scenes) + 1,
        "energy_peaks": len(energy["peaks"]),
        "notes": notes,
    }
    return {
        "assets": [
            _asset_dict("transcript", tr_rel, tr_size, {"engine": engine_id}),
            _asset_dict("scenes", sc_rel, sc_size),
            _asset_dict("energy", en_rel, en_size),
        ],
        "video": {"meta": {"understand": summary}},
    }


STAGE_FUNCS = {Stage.ingest: run_ingest, Stage.understand: run_understand}


# ---------- job handler ----------


def _run(ctx: JobContext) -> dict:
    stage = Stage(ctx.payload["stage"])
    if ctx.video_id is None:
        raise PermanentError("stage job without video")
    video, assets = _load(ctx.video_id)
    _mark_running(video.id, stage)
    result = STAGE_FUNCS[stage](ctx, video, assets)
    result["stage"] = stage.value
    return result


def _on_success(s: Session, job: Job, result: dict) -> None:
    video = s.get(Video, job.video_id, with_for_update=True)
    if video is None or video.status == VideoStatus.cancelled:
        return
    for a in result.get("assets", []):
        stmt = insert(Asset).values(video_id=video.id, kind=a["kind"], path=a["path"], size_bytes=a["size_bytes"], meta=a["meta"])
        s.execute(
            stmt.on_conflict_do_update(
                constraint="uq_asset_video_kind",
                set_={"path": stmt.excluded.path, "size_bytes": stmt.excluded.size_bytes, "meta": stmt.excluded.meta},
            )
        )
    upd = result.get("video", {})
    if upd.get("duration_s") is not None:
        video.duration_s = upd["duration_s"]
    if upd.get("meta"):
        video.meta = {**(video.meta or {}), **upd["meta"]}

    stage = Stage(result["stage"])
    idx = PIPELINE.index(stage)
    if idx + 1 < len(PIPELINE):
        nxt = PIPELINE[idx + 1]
        video.stage = nxt
        video.status = VideoStatus.queued
        enqueue_stage(s, video, nxt)
    else:
        video.status = VideoStatus.ready
        video.progress = 100


def _on_failure(s: Session, job: Job) -> None:
    video = s.get(Video, job.video_id, with_for_update=True)
    if video is None or video.status == VideoStatus.cancelled:
        return
    video.status = VideoStatus.failed
    video.error = job.last_error


def register_handlers() -> None:
    register(JOB_KIND, Handler(run=_run, on_success=_on_success, on_failure=_on_failure))
