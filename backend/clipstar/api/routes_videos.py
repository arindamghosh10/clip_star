import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..jobs import queue
from ..models import Asset, Clip, Job, JobStatus, Video, VideoStatus, Workspace
from ..pipeline.stages import enqueue_stage, start_pipeline
from ..storage import get_storage
from .deps import get_workspace
from .schemas import AssetOut, VideoDetail, VideoOut, VideoPatch

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _active_jobs(s: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not ids:
        return {}
    rows = s.scalars(select(Job).where(Job.video_id.in_(ids), Job.status.in_([JobStatus.queued, JobStatus.running])))
    return {j.video_id: j for j in rows}


def _out(v: Video, clips: int, job: Job | None, detail: bool = False):
    data = VideoOut.model_validate(v).model_dump()
    data["clips"] = clips
    if job:
        data["active_job_id"] = job.id
        if v.status in (VideoStatus.processing, VideoStatus.queued):
            data["progress"] = job.progress
    if detail:
        return VideoDetail(**data, assets=[AssetOut.model_validate(a) for a in v.assets])
    return VideoOut(**data)


def _get(s: Session, ws: Workspace, video_id: uuid.UUID) -> Video:
    v = s.get(Video, video_id)
    if v is None or v.workspace_id != ws.id:
        raise HTTPException(404, "Video not found.")
    return v


@router.get("", response_model=list[VideoOut])
def list_videos(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    videos = list(s.scalars(select(Video).where(Video.workspace_id == ws.id).order_by(Video.created_at.desc())))
    ids = [v.id for v in videos]
    counts = dict(s.execute(select(Clip.video_id, func.count()).where(Clip.video_id.in_(ids)).group_by(Clip.video_id)).all()) if ids else {}
    jobs = _active_jobs(s, ids)
    return [_out(v, counts.get(v.id, 0), jobs.get(v.id)) for v in videos]


@router.post("", response_model=VideoDetail, status_code=201)
def upload_video(
    file: UploadFile = File(...),
    captions: UploadFile | None = File(default=None),
    title: str | None = Form(default=None),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    st_cfg = get_settings()
    name = Path(file.filename or "video").name
    ext = Path(name).suffix.lower()
    if ext not in st_cfg.allowed_video_extensions:
        raise HTTPException(422, f"Unsupported file type '{ext or 'none'}'. Use one of: {', '.join(st_cfg.allowed_video_extensions)}.")
    cap_ext = None
    if captions is not None and captions.filename:
        cap_ext = Path(captions.filename).suffix.lower()
        if cap_ext not in st_cfg.allowed_caption_extensions:
            raise HTTPException(422, "Captions must be an .srt or .vtt file.")

    storage = get_storage()
    video = Video(workspace_id=ws.id, title=(title or Path(name).stem)[:300], source_filename=name[:300])
    s.add(video)
    s.flush()
    try:
        master_rel = storage.rel(video.id, f"master{ext}")
        size = storage.save_stream(file.file, master_rel, st_cfg.max_upload_bytes)
        if size == 0:
            raise ValueError("The uploaded file is empty.")
        video.size_bytes = size
        s.add(Asset(video_id=video.id, kind="master", path=master_rel, size_bytes=size, meta={"filename": name}))
        if captions is not None and cap_ext:
            cap_rel = storage.rel(video.id, f"captions{cap_ext}")
            cap_size = storage.save_stream(captions.file, cap_rel, 50 * 1024 * 1024)
            s.add(Asset(video_id=video.id, kind="captions", path=cap_rel, size_bytes=cap_size, meta={"filename": captions.filename}))
        start_pipeline(s, video)
        s.commit()
    except ValueError as e:
        s.rollback()
        storage.delete_video(video.id)
        raise HTTPException(422, str(e)) from e
    except Exception:
        s.rollback()
        storage.delete_video(video.id)
        raise
    s.refresh(video)
    return _out(video, 0, _active_jobs(s, [video.id]).get(video.id), detail=True)


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)


@router.post("/import", response_model=VideoDetail, status_code=201)
def import_video(body: ImportIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Add a video from a link (direct file, Dropbox or Google Drive). It downloads in the background, then processing starts."""
    from ..importer import KIND, normalize

    try:
        dl, source = normalize(body.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    title = (body.title or "").strip()
    video = Video(workspace_id=ws.id, title=(title or "Video from link")[:300], source_filename="(downloading)", meta={"import": {"url": body.url.strip(), "source": source}, "title_from_link": not title})
    s.add(video)
    s.flush()
    queue.enqueue(s, KIND, {"video_id": str(video.id), "url": dl, "source": source}, video_id=video.id, dedupe_key=f"video:{video.id}:import", max_attempts=3)
    s.commit()
    s.refresh(video)
    return _out(video, 0, _active_jobs(s, [video.id]).get(video.id), detail=True)


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    v = _get(s, ws, video_id)
    clips = s.scalar(select(func.count()).select_from(Clip).where(Clip.video_id == v.id)) or 0
    return _out(v, clips, _active_jobs(s, [v.id]).get(v.id), detail=True)


@router.patch("/{video_id}", response_model=VideoDetail)
def rename_video(video_id: uuid.UUID, body: VideoPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    v = _get(s, ws, video_id)
    v.title = body.title
    s.commit()
    return get_video(video_id, s, ws)


def _json_asset(s: Session, ws: Workspace, video_id: uuid.UUID, kind: str):
    v = _get(s, ws, video_id)
    a = s.scalar(select(Asset).where(Asset.video_id == v.id, Asset.kind == kind))
    if a is None:
        raise HTTPException(404, f"No {kind} yet. It is created by the Understand step.")
    return get_storage().read_json(a.path)


@router.get("/{video_id}/transcript")
def get_transcript(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _json_asset(s, ws, video_id, "transcript")


@router.get("/{video_id}/analysis")
def get_analysis(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return {"scenes": _json_asset(s, ws, video_id, "scenes"), "energy": _json_asset(s, ws, video_id, "energy")}


@router.get("/{video_id}/proxy")
def get_proxy(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    v = _get(s, ws, video_id)
    a = s.scalar(select(Asset).where(Asset.video_id == v.id, Asset.kind == "proxy"))
    if a is None:
        raise HTTPException(404, "No preview yet.")
    return FileResponse(get_storage().abs(a.path), media_type="video/mp4")


@router.post("/{video_id}/retry", response_model=VideoDetail)
def retry_video(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Re-run the stage the video stopped at."""
    v = _get(s, ws, video_id)
    if v.status not in (VideoStatus.failed, VideoStatus.cancelled):
        raise HTTPException(409, "Only failed or cancelled videos can be retried.")
    v.status = VideoStatus.queued
    v.error = None
    imp = (v.meta or {}).get("import")
    if imp and not s.scalar(select(Asset.id).where(Asset.video_id == v.id, Asset.kind == "master")):
        from ..importer import KIND, normalize

        dl, source = normalize(imp["url"])  # the download itself failed: try it again
        queue.enqueue(s, KIND, {"video_id": str(v.id), "url": dl, "source": source}, video_id=v.id, dedupe_key=f"video:{v.id}:import", max_attempts=3)
    else:
        enqueue_stage(s, v, v.stage)
    s.commit()
    return get_video(video_id, s, ws)


@router.post("/{video_id}/cancel", response_model=VideoDetail)
def cancel_video(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    v = _get(s, ws, video_id)
    if v.status not in (VideoStatus.queued, VideoStatus.processing):
        raise HTTPException(409, "This video isn't being processed.")
    for j in s.scalars(select(Job).where(Job.video_id == v.id, Job.status.in_([JobStatus.queued, JobStatus.running])).with_for_update()):
        queue.cancel(s, j)
    v.status = VideoStatus.cancelled
    s.commit()
    return get_video(video_id, s, ws)


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    v = _get(s, ws, video_id)
    for j in s.scalars(select(Job).where(Job.video_id == v.id, Job.status.in_([JobStatus.queued, JobStatus.running])).with_for_update()):
        queue.cancel(s, j)
    s.delete(v)
    s.commit()
    get_storage().delete_video(video_id)
