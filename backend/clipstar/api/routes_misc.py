import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import get_session
from ..engines.registry import ENGINES, chosen_engine_id, get_engine
from ..jobs.queue import utcnow
from ..media import tools_available
from ..models import Clip, ClipStatus, EngineChoice, Job, JobStatus, Stage, Video, WorkerHeartbeat, Workspace
from ..storage import get_storage
from .deps import get_workspace
from .schemas import ClipOut, ClipPatch, EngineOut, EngineSelect, Health, TranscriptReplace, WorkspacePatch

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=Health)
def health(s: Session = Depends(get_session)):
    try:
        s.execute(text("select 1"))
        db = True
    except Exception:
        db = False
    st = get_storage()
    writable = os.access(st.root, os.W_OK)
    tools = tools_available()
    workers = queued = failed = 0
    if db:
        workers = s.scalar(select(func.count()).select_from(WorkerHeartbeat).where(WorkerHeartbeat.last_seen > utcnow() - timedelta(minutes=2))) or 0
        queued = s.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.queued)) or 0
        failed = s.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.failed)) or 0
    return Health(
        ok=db and writable and tools["ffmpeg"] and tools["ffprobe"],
        database=db,
        storage_writable=writable,
        storage_free_gb=round(st.free_bytes() / 1024**3, 1),
        ffmpeg=tools["ffmpeg"],
        ffprobe=tools["ffprobe"],
        workers_online=workers,
        queued_jobs=queued,
        failed_jobs=failed,
    )


# ---------- engines ----------


@router.get("/engines", response_model=list[EngineOut])
def list_engines(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    out = []
    for e in ENGINES.values():
        h = e.check()
        out.append(
            EngineOut(
                id=e.info.id,
                stage=e.info.stage,
                name=e.info.name,
                kind=e.info.kind,
                description=e.info.description,
                ok=h.ok,
                message=h.message,
                selected=chosen_engine_id(s, ws.id, e.info.stage) == e.info.id,
                estimate=e.estimate(600),
            )
        )
    return out


@router.put("/engines/{stage}", response_model=list[EngineOut])
def select_engine(stage: Stage, body: EngineSelect, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    e = get_engine(stage, body.engine_id)
    if e is None:
        raise HTTPException(422, f"'{body.engine_id}' is not an engine for {stage.value}.")
    row = s.get(EngineChoice, (ws.id, stage))
    if row:
        row.engine_id = body.engine_id
    else:
        s.add(EngineChoice(workspace_id=ws.id, stage=stage, engine_id=body.engine_id))
    s.commit()
    return list_engines(s, ws)


# ---------- clips ----------


def _clip(s: Session, ws: Workspace, clip_id: uuid.UUID) -> Clip:
    c = s.scalar(select(Clip).join(Video).where(Clip.id == clip_id, Video.workspace_id == ws.id))
    if c is None:
        raise HTTPException(404, "Clip not found.")
    return c


@router.get("/clips", response_model=list[ClipOut])
def list_clips(video_id: uuid.UUID | None = None, status: str | None = None, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    q = select(Clip).join(Video).where(Video.workspace_id == ws.id)
    if video_id:
        q = q.where(Clip.video_id == video_id)
    if status:
        q = q.where(Clip.status == status)
    return list(s.scalars(q.order_by(Clip.score.desc())))


@router.get("/clips/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _clip(s, ws, clip_id)


ARCHIVED = "This video was archived to save space (its original file was deleted), so its clips can't be re-cut or re-rendered. Text and captions can still be edited."


@router.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(clip_id: uuid.UUID, body: ClipPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    from ..pipeline.package import PLATFORM_RULES, check_copy, normalize_tag
    from ..pipeline.stages import enqueue_clip_render

    c = s.scalar(select(Clip).join(Video).where(Clip.id == clip_id, Video.workspace_id == ws.id).with_for_update(of=Clip))
    if c is None:
        raise HTTPException(404, "Clip not found.")
    video = s.get(Video, c.video_id)
    data = body.model_dump(exclude_unset=True, by_alias=False)
    meta = dict(c.meta or {})
    rerender = False
    if (video.meta or {}).get("archived") and ("start_s" in data or "end_s" in data or "variants" in data):
        raise HTTPException(409, ARCHIVED)
    if (c.meta or {}).get("external") and ("start_s" in data or "end_s" in data or "variants" in data):
        raise HTTPException(409, f"This clip was made by {(c.meta or {}).get('external').title()}, so it can't be re-cut here. You can still change its text, approve or reject it.")

    if "start_s" in data or "end_s" in data:
        start = data.pop("start_s", c.start_s)
        end = data.pop("end_s", c.end_s)
        dur_total = video.duration_s or end
        if end > dur_total + 0.05:
            raise HTTPException(422, f"The clip can't end after the video ({dur_total:.1f}s).")
        if not 3 <= end - start <= 180:
            raise HTTPException(422, "A clip must be between 3 and 180 seconds long.")
        if (round(start, 3), round(end, 3)) != (round(c.start_s, 3), round(c.end_s, 3)):
            c.start_s, c.end_s = round(start, 3), round(min(end, dur_total), 3)
            meta["words"] = _words_in(video, c.start_s, c.end_s)
            meta["trimmed"] = True
            rerender = True

    if "variants" in data:
        vs = data.pop("variants")
        if len({v["id"] for v in vs}) != len(vs):
            raise HTTPException(422, "Each variant needs a different id.")
        if vs != list(c.variants or []):
            c.variants = [
                {"id": v["id"], "caption_style": v["caption_style"], "hook": v["hook"].strip().upper(), **{k: v[k] for k in ("zoom", "emoji", "broll") if v.get(k) is not None},
                 **({"music": {**v["music"], "track_id": str(v["music"]["track_id"]) if v["music"].get("track_id") else None}} if v.get("music") is not None else {})}
                for v in vs
            ]
            # drop renders of variants that no longer exist
            meta["renders"] = {k: v for k, v in (meta.get("renders") or {}).items() if k in {x["id"] for x in vs}}
            rerender = True

    if "copy_" in data:
        new = data.pop("copy_")
        unknown = [p for p in new if p not in PLATFORM_RULES]
        if unknown:
            raise HTTPException(422, f"Unknown platform: {', '.join(unknown)}.")
        merged = dict(c.copy or {})
        for p, cp in new.items():
            base = merged.get(p) if isinstance(merged.get(p), dict) else {}
            cp = {"title": base.get("title", ""), "caption": base.get("caption", ""), "hashtags": base.get("hashtags", []), **cp}  # unsent fields keep their value
            tags, seen = [], set()
            for h in cp["hashtags"]:
                t = normalize_tag(h)
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    tags.append(t)
            merged[p] = {"title": cp["title"].strip(), "caption": cp["caption"].strip(), "hashtags": tags}
        c.copy = merged
        meta["copy_edited"] = True

    if "ai_content" in data:
        meta["ai_content"] = bool(data.pop("ai_content"))
    for k, v in data.items():
        setattr(c, k, v)
    if isinstance(c.copy, dict) and all(isinstance(v, dict) for v in c.copy.values()):
        meta["preflight"] = check_copy(c.copy, c.end_s - c.start_s)
    c.meta = meta
    if rerender and c.status != ClipStatus.rejected:
        enqueue_clip_render(s, c)
    s.commit()
    s.refresh(c)
    return c


def _words_in(video: Video, start: float, end: float) -> list[dict]:
    """Caption words for a new clip range, from the video's transcript."""
    a = s_asset(video.id, "transcript")
    if a is None:
        return []
    tr = get_storage().read_json(a.path)
    out = []
    for seg in tr.get("segments", []):
        for w in seg.get("words") or []:
            if w["start"] >= start - 0.05 and w["end"] <= end + 0.05:
                out.append({"start": round(max(0.0, w["start"] - start), 3), "end": round(min(end, w["end"]) - start, 3), "word": w["word"].strip()})
    return out


def s_asset(video_id: uuid.UUID, kind: str):
    from ..db import session_scope
    from ..models import Asset

    with session_scope() as s2:
        return s2.scalar(select(Asset).where(Asset.video_id == video_id, Asset.kind == kind))


@router.post("/videos/{video_id}/transcript/replace")
def replace_in_transcript(video_id: uuid.UUID, body: TranscriptReplace, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Fix a misheard word everywhere: the transcript and every clip's captions. Changed clips re-render."""
    import re as _re

    from ..pipeline.stages import enqueue_clip_render

    v = s.get(Video, video_id)
    if v is None or v.workspace_id != ws.id:
        raise HTTPException(404, "Video not found.")
    a = s_asset(v.id, "transcript")
    if a is None:
        raise HTTPException(404, "This video has no transcript yet.")
    flags = 0 if body.match_case else _re.IGNORECASE
    pat = _re.compile(rf"(?<![\w']){_re.escape(body.find.strip())}(?![\w'])", flags)
    repl = body.replace.strip()

    def fix(text: str) -> tuple[str, int]:
        return pat.subn(lambda m: repl, text)

    st = get_storage()
    tr = st.read_json(a.path)
    count = 0
    for seg in tr.get("segments", []):
        seg["text"], n = fix(seg.get("text", ""))
        count += n
        for w in seg.get("words") or []:
            w["word"], _ = fix(w["word"])
    clips_changed = 0
    for c in s.scalars(select(Clip).where(Clip.video_id == v.id).with_for_update()):
        meta = dict(c.meta or {})
        changed = False
        new_words = []
        for w in meta.get("words", []):
            nw, n = fix(w["word"])
            changed |= n > 0
            new_words.append({**w, "word": nw})
        title, n = fix(c.title)
        changed |= n > 0
        if changed:
            meta["words"] = new_words
            c.meta = meta
            c.title = title or c.title
            clips_changed += 1
            if c.status != ClipStatus.rejected:
                enqueue_clip_render(s, c)
    if count == 0 and clips_changed == 0:
        raise HTTPException(404, f'"{body.find}" was not found in the transcript.')
    st.write_json(a.path, tr)
    s.commit()
    return {"replaced": count, "clips_changed": clips_changed}


class SegmentEdit(BaseModel):
    index: int = Field(ge=0)
    text: str = Field(max_length=2000)


class TranscriptEdits(BaseModel):
    edits: list[SegmentEdit] = Field(min_length=1, max_length=2000)


@router.put("/videos/{video_id}/transcript/segments")
def edit_transcript(video_id: uuid.UUID, body: TranscriptEdits, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Correct transcript lines by hand. Clips that contain an edited line get new captions and re-render."""
    from ..pipeline.stages import enqueue_clip_render
    from ..pipeline.transcript_edit import apply_edits

    v = s.get(Video, video_id)
    if v is None or v.workspace_id != ws.id:
        raise HTTPException(404, "Video not found.")
    a = s_asset(v.id, "transcript")
    if a is None:
        raise HTTPException(404, "This video has no transcript yet.")
    st = get_storage()
    tr = st.read_json(a.path)
    try:
        ranges = apply_edits(tr, [e.model_dump() for e in body.edits])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not ranges:
        return {"segments_changed": 0, "clips_changed": 0}
    st.write_json(a.path, tr)
    archived = bool((v.meta or {}).get("archived"))
    clips_changed = 0
    for c in s.scalars(select(Clip).where(Clip.video_id == v.id).with_for_update()):
        if (c.meta or {}).get("external") or not any(r0 < c.end_s and r1 > c.start_s for r0, r1 in ranges):
            continue
        meta = dict(c.meta or {})
        meta["words"] = _words_in(v, c.start_s, c.end_s)
        c.meta = meta
        clips_changed += 1
        if c.status != ClipStatus.rejected and not archived:
            enqueue_clip_render(s, c)
    s.commit()
    return {"segments_changed": len(ranges), "clips_changed": clips_changed, "rerendered": 0 if archived else clips_changed}


class DubIn(BaseModel):
    lang: str = Field(min_length=2, max_length=5)
    variant: str = Field(default="A", pattern=r"^[AB]$")


class ExternalIn(BaseModel):
    vendor: str = Field(pattern=r"^(klap|vizard)$")


@router.get("/external-clippers")
def external_clippers():
    from .. import external_clippers as ec

    return [{"id": k, "name": v, "configured": ec.configured(k)} for k, v in ec.VENDORS.items()]


@router.post("/videos/{video_id}/external-clips", status_code=202)
def external_clips(video_id: uuid.UUID, body: ExternalIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Ask Klap or Vizard (your own account) to clip this video; their clips arrive in Clips for review."""
    from .. import external_clippers as ec
    from ..config import get_settings
    from ..jobs import queue

    v = s.get(Video, video_id)
    if v is None or v.workspace_id != ws.id:
        raise HTTPException(404, "Video not found.")
    if not ec.configured(body.vendor):
        raise HTTPException(409, f"{ec.VENDORS[body.vendor]} isn't set up. Add CLIPSTAR_{body.vendor.upper()}_API_KEY on the server.")
    if not get_settings().public_media_url:
        raise HTTPException(409, f"{ec.VENDORS[body.vendor]} downloads the video itself, so this server must be reachable from the internet. Set CLIPSTAR_PUBLIC_MEDIA_URL.")
    if (v.meta or {}).get("archived"):
        raise HTTPException(409, ARCHIVED)
    job = queue.enqueue(s, ec.KIND, {"video_id": str(v.id), "vendor": body.vendor}, video_id=v.id, dedupe_key=f"video:{v.id}:external:{body.vendor}", max_attempts=2)
    s.commit()
    return {"job_id": str(job.id)}


@router.get("/dubbing")
def dubbing_info():
    from .. import dubbing

    return {"enabled": dubbing.enabled(), "languages": dubbing.LANGS}


@router.post("/clips/{clip_id}/dubs", status_code=202)
def dub_clip(clip_id: uuid.UUID, body: DubIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Dub one version of the clip into another language with ElevenLabs (paid connector)."""
    from .. import dubbing
    from ..jobs import queue

    if not dubbing.enabled():
        raise HTTPException(409, "Dubbing isn't set up. Add your ElevenLabs key (CLIPSTAR_ELEVENLABS_API_KEY) on the server.")
    if body.lang not in dubbing.LANGS:
        raise HTTPException(422, f"Choose one of: {', '.join(sorted(dubbing.LANGS))}.")
    c = _clip(s, ws, clip_id)
    _variant_ok(c, body.variant)
    if (c.meta or {}).get("external"):
        raise HTTPException(409, "Clips from external services can't be dubbed here (their timing isn't known).")
    v = s.get(Video, c.video_id)
    if (v.meta or {}).get("archived"):
        raise HTTPException(409, ARCHIVED)
    job = queue.enqueue(s, dubbing.KIND, {"clip_id": str(c.id), "lang": body.lang, "variant": body.variant}, video_id=c.video_id, dedupe_key=f"clip:{c.id}:dub:{body.variant}-{body.lang}", max_attempts=3)
    s.commit()
    return {"job_id": str(job.id), "variant": f"{body.variant}-{body.lang}"}


@router.delete("/clips/{clip_id}/dubs/{dub_id}", status_code=204)
def remove_dub(clip_id: uuid.UUID, dub_id: str, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    c = _clip(s, ws, clip_id)
    c = s.get(Clip, c.id, with_for_update=True)
    meta = dict(c.meta or {})
    dubs = dict(meta.get("dubs") or {})
    d = dubs.pop(dub_id, None)
    if d is None:
        raise HTTPException(404, "No such dubbed version.")
    renders = dict(meta.get("renders") or {})
    r = renders.pop(dub_id, None)
    meta["dubs"], meta["renders"] = dubs, renders
    c.meta = meta
    s.commit()
    st = get_storage()
    for rel in (d.get("audio"), (r or {}).get("path"), (r or {}).get("cover")):
        if rel:
            try:
                st.abs(rel).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


@router.get("/clips/{clip_id}/media/{variant}")
def clip_media(clip_id: uuid.UUID, variant: str, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _render_file(_clip(s, ws, clip_id), variant, "path", "video/mp4")


@router.get("/clips/{clip_id}/cover/{variant}")
def clip_cover(clip_id: uuid.UUID, variant: str, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    from ..pipeline.covers import cover_rel

    rel = cover_rel(_clip(s, ws, clip_id), variant)
    st = get_storage()
    if not rel or not st.exists(rel):
        raise HTTPException(404, "This clip hasn't been rendered yet.")
    return FileResponse(st.abs(rel), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


def _set_custom_cover(s: Session, c: Clip, variant: str, rel: str | None) -> dict:
    meta = dict(c.meta or {})
    covers = dict(meta.get("custom_covers") or {})
    old = covers.get(variant)
    if rel:
        covers[variant] = rel
    else:
        covers.pop(variant, None)
    meta["custom_covers"] = covers
    c.meta = meta
    s.commit()
    if old and old != rel:
        try:
            get_storage().abs(old).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    return {"variant": variant, "custom": bool(rel), "key": (rel or "auto").rsplit("/", 1)[-1]}


def _variant_ok(c: Clip, variant: str) -> None:
    if variant not in {v.get("id") for v in (c.variants or [])}:
        raise HTTPException(404, f"This clip has no version {variant}.")


@router.post("/clips/{clip_id}/cover/{variant}")
async def upload_cover(clip_id: uuid.UUID, variant: str, file: UploadFile = File(...), s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Use your own cover image (JPEG, PNG or WebP). It's fitted to 9:16 and kept through re-renders."""
    from ..pipeline.covers import MAX_BYTES, save_cover

    c = _clip(s, ws, clip_id)
    _variant_ok(c, variant)
    data = await file.read(MAX_BYTES + 1)
    try:
        rel = save_cover(c.video_id, c.id, variant, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    c = s.get(Clip, clip_id, with_for_update=True)
    return _set_custom_cover(s, c, variant, rel)


class FrameIn(BaseModel):
    at_s: float = Field(ge=0, le=600)


@router.post("/clips/{clip_id}/cover/{variant}/frame")
def cover_from_frame(clip_id: uuid.UUID, variant: str, body: FrameIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Use a still from the rendered clip at `at_s` seconds as the cover."""
    from ..errors import ClipstarError
    from ..pipeline.covers import frame_cover

    c = _clip(s, ws, clip_id)
    _variant_ok(c, variant)
    r = ((c.meta or {}).get("renders") or {}).get(variant)
    if not r or not get_storage().exists(r.get("path", "")):
        raise HTTPException(409, "Render this version first.")
    if body.at_s > c.end_s - c.start_s:
        raise HTTPException(422, "That time is past the end of the clip.")
    try:
        rel = frame_cover(c.video_id, c.id, variant, r["path"], body.at_s)
    except (ValueError, ClipstarError) as e:
        raise HTTPException(422, getattr(e, "user_message", None) or str(e)) from e
    c = s.get(Clip, clip_id, with_for_update=True)
    return _set_custom_cover(s, c, variant, rel)


@router.delete("/clips/{clip_id}/cover/{variant}")
def reset_cover(clip_id: uuid.UUID, variant: str, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Go back to the automatic cover."""
    c = _clip(s, ws, clip_id)
    c = s.get(Clip, c.id, with_for_update=True)
    return _set_custom_cover(s, c, variant, None)


def _render_file(c: Clip, variant: str, field: str, media_type: str):
    r = ((c.meta or {}).get("renders") or {}).get(variant)
    st = get_storage()
    if not r or not r.get(field) or not st.exists(r[field]):
        raise HTTPException(404, "This clip hasn't been rendered yet.")
    return FileResponse(st.abs(r[field]), media_type=media_type, headers={"Cache-Control": "private, max-age=60"})


@router.post("/clips/{clip_id}/render", status_code=202)
def rerender_clip(clip_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    from ..pipeline.stages import enqueue_clip_render

    c = _clip(s, ws, clip_id)
    if c.status == ClipStatus.rejected:
        raise HTTPException(409, "Rejected clips aren't rendered. Approve or restore it first.")
    if ((v := s.get(Video, c.video_id)) and (v.meta or {}).get("archived")):
        raise HTTPException(409, ARCHIVED)
    if (c.meta or {}).get("external"):
        raise HTTPException(409, "This clip came finished from an external service, so clip_star doesn't re-render it.")
    job = enqueue_clip_render(s, c)
    s.commit()
    return {"job_id": str(job.id)}


# ---------- workspace settings ----------


@router.get("/workspace")
def get_ws(ws: Workspace = Depends(get_workspace)):
    return {"id": str(ws.id), "name": ws.name, "settings": ws.settings}


@router.patch("/workspace")
def patch_ws(body: WorkspacePatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    if body.name is not None:
        ws.name = body.name.strip()
    if body.settings is not None:
        new = {k: (v.value if hasattr(v, "value") else v) for k, v in body.settings.model_dump(exclude_unset=True).items()}
        if "platforms" in new:
            new["platforms"] = [getattr(p, "value", p) for p in new["platforms"]]
        merged = {**(ws.settings or {}), **new}
        lo, hi = merged.get("clip_min_s", 15), merged.get("clip_max_s", 60)
        if lo >= hi:
            raise HTTPException(422, "The shortest clip length must be less than the longest.")
        if not lo <= merged.get("clip_target_s", lo) <= hi:
            merged["clip_target_s"] = round((lo + hi) / 2, 1)
        ws.settings = merged
    s.commit()
    return {"id": str(ws.id), "name": ws.name, "settings": ws.settings}
