import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import get_session
from ..engines.registry import ENGINES, chosen_engine_id
from ..jobs.queue import utcnow
from ..media import tools_available
from ..models import Clip, EngineChoice, Job, JobStatus, Stage, Video, WorkerHeartbeat, Workspace
from ..storage import get_storage
from .deps import get_workspace
from .schemas import ClipOut, ClipPatch, EngineOut, EngineSelect, Health

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
            )
        )
    return out


@router.put("/engines/{stage}", response_model=list[EngineOut])
def select_engine(stage: Stage, body: EngineSelect, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    e = ENGINES.get(body.engine_id)
    if e is None or e.info.stage != stage:
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


@router.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(clip_id: uuid.UUID, body: ClipPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    c = _clip(s, ws, clip_id)
    data = body.model_dump(exclude_unset=True, by_alias=False)
    if "copy_" in data:
        c.copy = {**(c.copy or {}), **data.pop("copy_")}
    for k, v in data.items():
        setattr(c, k, v)
    s.commit()
    return c


# ---------- workspace settings ----------


@router.get("/workspace")
def get_ws(ws: Workspace = Depends(get_workspace)):
    return {"id": str(ws.id), "name": ws.name, "settings": ws.settings}


@router.patch("/workspace")
def patch_ws(body: dict, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    ws = s.merge(ws)
    if "name" in body:
        name = str(body["name"]).strip()
        if not 1 <= len(name) <= 200:
            raise HTTPException(422, "Name must be 1-200 characters.")
        ws.name = name
    if "settings" in body:
        if not isinstance(body["settings"], dict):
            raise HTTPException(422, "settings must be an object.")
        ws.settings = {**(ws.settings or {}), **body["settings"]}
    s.commit()
    return {"id": str(ws.id), "name": ws.name, "settings": ws.settings}
