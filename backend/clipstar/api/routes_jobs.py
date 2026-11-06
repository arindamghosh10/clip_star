import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_session
from ..jobs import queue
from ..models import Job, JobStatus, Video, VideoStatus, Workspace
from .deps import get_workspace
from .schemas import JobDetail, JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get(s: Session, ws: Workspace, job_id: uuid.UUID, lock: bool = False) -> Job:
    q = select(Job).where(Job.id == job_id).options(selectinload(Job.events))
    if lock:
        q = q.with_for_update(of=Job)
    job = s.scalar(q)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.video_id:
        v = s.get(Video, job.video_id)
        if v is None or v.workspace_id != ws.id:
            raise HTTPException(404, "Job not found.")
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    video_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    q = select(Job).outerjoin(Video, Video.id == Job.video_id).where((Video.workspace_id == ws.id) | (Job.video_id.is_(None)))
    if status:
        q = q.where(Job.status == status)
    if video_id:
        q = q.where(Job.video_id == video_id)
    return list(s.scalars(q.order_by(Job.created_at.desc()).limit(limit)))


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _get(s, ws, job_id)


@router.post("/{job_id}/retry", response_model=JobDetail)
def retry_job(job_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    job = _get(s, ws, job_id, lock=True)
    try:
        queue.retry_now(s, job)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if job.video_id:
        v = s.get(Video, job.video_id, with_for_update=True)
        if v and v.status in (VideoStatus.failed, VideoStatus.cancelled):
            v.status = VideoStatus.queued
            v.error = None
    s.commit()
    s.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobDetail)
def cancel_job(job_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    job = _get(s, ws, job_id, lock=True)
    try:
        queue.cancel(s, job)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if job.video_id:
        v = s.get(Video, job.video_id, with_for_update=True)
        if v and v.status in (VideoStatus.queued, VideoStatus.processing):
            v.status = VideoStatus.cancelled
    s.commit()
    s.refresh(job)
    return job
