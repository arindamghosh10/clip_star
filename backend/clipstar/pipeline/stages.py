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
from ..engines.registry import chosen_engine_id, get_engine
from ..errors import PermanentError
from ..jobs import queue
from ..jobs.runtime import Handler, JobContext, register
from ..media import probe, run_ffmpeg
from ..models import Asset, Clip, ClipStatus, Job, Post, Stage, Video, VideoStatus, Workspace
from ..storage import get_storage
from .analysis import audio_energy, detect_scenes
from .framing import plan_layout
from .moments import MomentSettings, Signals, build_sentences, clip_words, finalize, make_hook, overlap
from .package import ClipContext, PackageSettings, finalize_copy
from .render import RenderSpec, render_clip

PIPELINE: list[Stage] = [Stage.ingest, Stage.understand, Stage.moments, Stage.edit, Stage.package]
CLIP_RENDER_KIND = "clip.render"
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
        engine = get_engine(Stage.understand, engine_id)
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


# ---------- stage: find moments ----------


def _read(assets: dict[str, Asset], kind: str, default=None):
    a = assets.get(kind)
    st = get_storage()
    if a is None or not st.exists(a.path):
        if default is not None:
            return default
        raise PermanentError(f"{kind} missing", user_message=f"The {kind} file is missing. Retry the Understand step.")
    return st.read_json(a.path)


def run_moments(ctx: JobContext, video: Video, assets: dict[str, Asset]) -> dict:
    transcript = _read(assets, "transcript")
    cuts = _read(assets, "scenes", {"cuts": []}).get("cuts", [])
    energy = _read(assets, "energy", {"window_s": 1.0, "values": [], "peaks": []})
    duration = video.duration_s or transcript.get("duration") or 0.0
    with session_scope() as s:
        ws = s.get(Workspace, video.workspace_id)
        st = MomentSettings.from_workspace(ws.settings if ws else {})
        engine_id = chosen_engine_id(s, video.workspace_id, Stage.moments) or "rules"
    engine = get_engine(Stage.moments, engine_id) or get_engine(Stage.moments, "rules")
    sents = build_sentences(transcript)
    sig = Signals(energy, cuts)
    ctx.progress(5, f"{len(sents)} sentences; finding moments with {engine.info.name}")
    cands, notes = engine.find(ctx, sents, sig, st, duration)
    final, more = finalize(cands, sents, st, duration)
    notes += more
    ctx.progress(95, f"{len(final)} moments chosen")

    clips = []
    for c in final:
        # small padding so the first and last words aren't clipped, without running into neighbours
        prev_end = sents[c.start_id - 1].end if c.start_id > 0 else 0.0
        next_start = sents[c.end_id + 1].start if 0 <= c.end_id < len(sents) - 1 else duration
        start = max(prev_end, c.start - 0.15, 0.0) if c.start_id >= 0 else c.start
        end = min(next_start, c.end + 0.4, duration) if c.start_id >= 0 else c.end
        c.start, c.end = start, end
        alt = make_hook(sents[c.start_id + 1].text) if 0 <= c.start_id < c.end_id else ""
        variants = [{"id": "A", "caption_style": st_caption(video), "hook": c.hook}]
        if st_variants(video) > 1:
            variants.append({"id": "B", "caption_style": "clean", "hook": alt if alt and alt != c.hook else c.hook})
        clips.append(
            {
                "title": c.title,
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "score": c.score,
                "reason": c.reason,
                "hook": c.hook,
                "engine": c.engine,
                "variants": variants,
                "meta": {"words": clip_words(sents, c), "features": c.features, "heuristic": c.heuristic, "sentences": [c.start_id, c.end_id]},
            }
        )
    return {"clips": clips, "video": {"meta": {"moments": {"engine": engine_id, "count": len(clips), "notes": notes}}}}


def _ws_settings(video: Video) -> dict:
    with session_scope() as s:
        ws = s.get(Workspace, video.workspace_id)
        return dict(ws.settings or {}) if ws else {}


def st_caption(video: Video) -> str:
    v = _ws_settings(video).get("caption_style")
    return v if v in ("bold-pop", "clean") else "bold-pop"


def st_variants(video: Video) -> int:
    v = _ws_settings(video).get("variants", 2)
    return 2 if v not in (1, 2) else v


# ---------- stage: edit (render) ----------


def render_clips(ctx: JobContext, video: Video, assets: dict[str, Asset], clip_ids: list[uuid.UUID] | None = None, p0: float = 0, p1: float = 100) -> dict:
    stg = get_storage()
    master = assets.get("master")
    proxy = assets.get("proxy")
    if master is None or not stg.exists(master.path) or proxy is None or not stg.exists(proxy.path):
        raise PermanentError("media missing", user_message="The video files are missing. Retry from the Ingest step.")
    pr = (video.meta or {}).get("probe") or probe(stg.abs(master.path)).as_dict()
    cuts = _read(assets, "scenes", {"cuts": []}).get("cuts", [])
    with session_scope() as s:
        q = select(Clip).where(Clip.video_id == video.id, Clip.status != ClipStatus.rejected)
        if clip_ids:
            q = q.where(Clip.id.in_(clip_ids))
        clips = [(c.id, c.start_s, c.end_s, list(c.variants or []), dict(c.meta or {})) for c in s.scalars(q.order_by(Clip.score.desc()))]
    jobs = [(cid, a, b, v, meta) for cid, a, b, vs, meta in clips for v in vs]
    done = failed = skipped = 0
    layouts: dict = {}  # one framing analysis per clip, shared by its variants
    for k, (cid, a, b, variant, meta) in enumerate(jobs):
        ctx.check()
        base = p0 + (p1 - p0) * k / max(1, len(jobs))
        span = (p1 - p0) / max(1, len(jobs))
        if cid not in layouts:
            layouts[cid] = plan_layout(stg.abs(proxy.path), a, b, cuts, pr["width"], pr["height"])
        layout = layouts[cid]
        spec = RenderSpec(start=a, end=b, words=meta.get("words", []), hook=variant.get("hook", ""), caption_style=variant.get("caption_style", "bold-pop"), layout=layout)
        key = spec.key()
        vid_rel = stg.rel(video.id, f"clips/{cid}/{variant['id']}.mp4")
        cov_rel = stg.rel(video.id, f"clips/{cid}/{variant['id']}.jpg")
        prev = (meta.get("renders") or {}).get(variant["id"])
        if prev and prev.get("key") == key and stg.exists(vid_rel) and stg.exists(cov_rel):
            skipped += 1
            continue
        ctx.progress(base, f"Rendering clip {k + 1} of {len(jobs)} ({variant['id']}, {layout.mode})")
        try:
            info = render_clip(stg.abs(master.path), pr["width"], pr["height"], pr.get("has_audio", True), spec, stg.abs(vid_rel), stg.abs(cov_rel), lambda p: ctx.progress(base + span * p / 100), ctx.check)
        except PermanentError as e:
            failed += 1
            _save_render(cid, variant["id"], None, e.user_message)
            continue
        _save_render(cid, variant["id"], {"key": key, "path": vid_rel, "cover": cov_rel, "layout": layout.as_dict(), **info}, None)
        done += 1
    if jobs and failed == len(jobs):
        raise PermanentError("all renders failed", user_message="None of the clips could be rendered. See the clip errors for details.")
    return {"rendered": done, "failed": failed, "skipped": skipped}


def _save_render(clip_id: uuid.UUID, variant: str, render: dict | None, error: str | None) -> None:
    """Saved right away, so a retry after a crash skips clips that are already rendered."""
    with session_scope() as s:
        c = s.get(Clip, clip_id, with_for_update=True)
        if c is None:
            return
        meta = dict(c.meta or {})
        renders = dict(meta.get("renders") or {})
        errors = dict(meta.get("render_errors") or {})
        if render:
            renders[variant] = render
            errors.pop(variant, None)
        else:
            errors[variant] = error
        meta["renders"], meta["render_errors"] = renders, errors
        c.meta = meta


def run_edit(ctx: JobContext, video: Video, assets: dict[str, Asset]) -> dict:
    res = render_clips(ctx, video, assets)
    return {"video": {"meta": {"edit": res}}}


# ---------- stage: package ----------


def clip_text(meta: dict) -> str:
    return " ".join(w["word"] for w in meta.get("words", [])).strip()


def run_package(ctx: JobContext, video: Video, assets: dict[str, Asset]) -> dict:
    with session_scope() as s:
        ws = s.get(Workspace, video.workspace_id)
        st = PackageSettings.from_workspace(ws.settings if ws else {})
        engine_id = chosen_engine_id(s, video.workspace_id, Stage.package) or "templates"
        clips = [
            (c.id, c.title, c.hook, dict(c.meta or {}), c.end_s - c.start_s)
            for c in s.scalars(select(Clip).where(Clip.video_id == video.id, Clip.status != ClipStatus.rejected).order_by(Clip.score.desc()))
        ]
    engine = get_engine(Stage.package, engine_id) or get_engine(Stage.package, "templates")
    out: dict[str, dict] = {}
    notes: list[str] = []
    for k, (cid, title, hook, meta, dur) in enumerate(clips):
        ctx.progress(100 * k / max(1, len(clips)), f"Writing captions for clip {k + 1} of {len(clips)}")
        if meta.get("copy_edited"):
            continue  # never overwrite text the creator edited by hand
        cc = ClipContext(title=title, hook=hook, text=clip_text(meta) or title, duration=dur)
        raw, n1 = engine.write(ctx, cc, st)
        copy, pre, n2 = finalize_copy(raw, cc, st)
        for n in n1 + n2:
            if n not in notes:
                notes.append(n)
        out[str(cid)] = {"copy": copy, "preflight": pre, "engine": engine.info.id}
    return {"package": out, "auto_approve": st.auto_approve_score, "video": {"meta": {"package": {"engine": engine.info.id, "clips": len(out), "notes": notes}}}}


STAGE_FUNCS = {Stage.ingest: run_ingest, Stage.understand: run_understand, Stage.moments: run_moments, Stage.edit: run_edit, Stage.package: run_package}


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
    if "clips" in result:
        _replace_clips(s, video, result["clips"])
    if "package" in result:
        _apply_package(s, video, result["package"], result.get("auto_approve"))
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
        from ..publishing.service import queue_rules

        queue_rules(s, video.id)  # automation rules may turn the new clips into a batch


def _replace_clips(s: Session, video: Video, new: list[dict]) -> None:
    """Re-running Find moments replaces undecided clips; approved/rejected ones and clips in posts stay."""
    existing = list(s.scalars(select(Clip).where(Clip.video_id == video.id)))
    used = set(s.scalars(select(Post.clip_id).where(Post.clip_id.in_([c.id for c in existing])))) if existing else set()
    kept = []
    for c in existing:
        if c.status == ClipStatus.pending and c.id not in used:
            s.delete(c)
        else:
            kept.append(c)
    s.flush()
    from .moments import Candidate

    for d in new:
        cand = Candidate(-1, -1, d["start_s"], d["end_s"])
        if any(overlap(cand, Candidate(-1, -1, k.start_s, k.end_s)) > 0.5 for k in kept):
            continue
        s.add(Clip(video_id=video.id, **d))


def _apply_package(s: Session, video: Video, package: dict, auto_approve: int | None) -> None:
    for cid, p in package.items():
        c = s.get(Clip, uuid.UUID(cid), with_for_update=True)
        if c is None or c.video_id != video.id:
            continue
        meta = dict(c.meta or {})
        if meta.get("copy_edited"):
            continue  # edited while this job ran
        c.copy = p["copy"]
        meta["preflight"] = p["preflight"]
        meta["copy_engine"] = p["engine"]
        c.meta = meta
        if auto_approve and c.status == ClipStatus.pending and c.score >= auto_approve:
            c.status = ClipStatus.approved
            meta["auto_approved"] = True
            c.meta = meta


def _on_failure(s: Session, job: Job) -> None:
    video = s.get(Video, job.video_id, with_for_update=True)
    if video is None or video.status == VideoStatus.cancelled:
        return
    video.status = VideoStatus.failed
    video.error = job.last_error


def _run_clip_render(ctx: JobContext) -> dict:
    clip_id = uuid.UUID(ctx.payload["clip_id"])
    if ctx.video_id is None:
        raise PermanentError("render job without video")
    video, assets = _load(ctx.video_id)
    return render_clips(ctx, video, assets, clip_ids=[clip_id])


def enqueue_clip_render(s: Session, clip: Clip) -> Job:
    return queue.enqueue(s, CLIP_RENDER_KIND, {"clip_id": str(clip.id)}, video_id=clip.video_id, dedupe_key=f"clip:{clip.id}:render", priority=50)


def register_handlers() -> None:
    register(JOB_KIND, Handler(run=_run, on_success=_on_success, on_failure=_on_failure))
    register(CLIP_RENDER_KIND, Handler(run=_run_clip_render))
