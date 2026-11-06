"""Postgres-backed durable job queue.

Guarantees:
- A job is run by at most one worker at a time (row lock + lease owner check).
- A crashed worker's job is picked up again once its lease expires.
- Failures retry with exponential backoff + jitter; permanent errors stop at once.
- Completion and its follow-up work (e.g. enqueueing the next stage) commit in one transaction.
"""

from __future__ import annotations

import random
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ClipstarError
from ..models import Job, JobEvent, JobStatus

ACTIVE = (JobStatus.queued, JobStatus.running)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_event(s: Session, job_id: uuid.UUID, type_: str, message: str = "", data: dict | None = None) -> None:
    s.add(JobEvent(job_id=job_id, type=type_, message=message[:4000], data=data or {}))


def enqueue(
    s: Session,
    kind: str,
    payload: dict | None = None,
    *,
    video_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    priority: int = 100,
    max_attempts: int | None = None,
) -> Job:
    """Add a job. With a dedupe_key, an already active job with that key is returned instead of a duplicate."""
    if dedupe_key:
        existing = s.scalar(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(ACTIVE)))
        if existing:
            return existing
    job = Job(
        kind=kind,
        payload=payload or {},
        video_id=video_id,
        dedupe_key=dedupe_key,
        run_after=run_after or utcnow(),
        priority=priority,
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    if dedupe_key:
        # Guard against a concurrent enqueue of the same key (partial unique index).
        try:
            with s.begin_nested():
                s.add(job)
                s.flush()
        except IntegrityError:
            existing = s.scalar(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(ACTIVE)))
            if existing:
                return existing
            raise
    else:
        s.add(job)
        s.flush()
    add_event(s, job.id, "queued", f"{kind} queued")
    return job


_CLAIM_SQL = text(
    """
    UPDATE jobs SET
        status = 'running',
        attempts = attempts + 1,
        locked_by = :worker,
        lease_until = now() + make_interval(secs => :lease),
        updated_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE (status = 'queued' AND run_after <= now())
           OR (status = 'running' AND lease_until < now())
        ORDER BY priority, run_after
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id
    """
)


def claim(s: Session, worker_id: str, lease_seconds: int | None = None) -> Job | None:
    """Take the next runnable job (including ones whose worker died). Commits."""
    lease = lease_seconds or get_settings().worker_lease_seconds
    row = s.execute(_CLAIM_SQL, {"worker": worker_id, "lease": lease}).first()
    if not row:
        s.commit()
        return None
    job = s.get(Job, row.id, populate_existing=True)
    assert job is not None
    if job.attempts > job.max_attempts:
        # Reclaimed after a crash, but it has already used all attempts.
        _finish_failed(s, job, "Worker stopped while running this job too many times.", "permanent")
        s.commit()
        return None
    add_event(s, job.id, "started", f"attempt {job.attempts} of {job.max_attempts}", {"worker": worker_id})
    s.commit()
    return job


def renew_lease(s: Session, job_id: uuid.UUID, worker_id: str, lease_seconds: int | None = None) -> bool:
    """Extend the lease. Returns False if this worker no longer owns the job (stop work)."""
    lease = lease_seconds or get_settings().worker_lease_seconds
    res = s.execute(
        update(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.running)
        .values(lease_until=utcnow() + timedelta(seconds=lease))
    )
    s.commit()
    return res.rowcount == 1


def lock_owned(s: Session, job_id: uuid.UUID, worker_id: str) -> Job | None:
    """Row-lock the job if this worker still owns it. Used before writing a result."""
    return s.scalar(
        select(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.running)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def mark_succeeded(s: Session, job: Job, result: dict | None) -> None:
    job.status = JobStatus.succeeded
    job.result = result or {}
    job.progress = 100
    job.lease_until = None
    job.locked_by = None
    job.last_error = None
    job.error_kind = None
    job.finished_at = utcnow()
    add_event(s, job.id, "succeeded")


def backoff_seconds(attempt: int) -> float:
    st = get_settings()
    delay = min(st.job_backoff_max_seconds, st.job_backoff_base_seconds * (2 ** max(0, attempt - 1)))
    return delay * random.uniform(0.8, 1.2)


def _finish_failed(s: Session, job: Job, message: str, kind: str) -> None:
    job.status = JobStatus.failed
    job.last_error = message
    job.error_kind = kind
    job.lease_until = None
    job.locked_by = None
    job.finished_at = utcnow()
    add_event(s, job.id, "failed", message, {"error_kind": kind})


def mark_failed(s: Session, job: Job, exc: BaseException) -> bool:
    """Record a failure. Returns True if the job will be retried, False if it is finished as failed."""
    if isinstance(exc, ClipstarError):
        message, retryable = exc.user_message, exc.retryable
    else:
        message, retryable = f"{type(exc).__name__}: {exc}", True
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-6000:]

    if retryable and job.attempts < job.max_attempts:
        delay = backoff_seconds(job.attempts)
        job.status = JobStatus.queued
        job.run_after = utcnow() + timedelta(seconds=delay)
        job.last_error = message
        job.error_kind = "retryable"
        job.lease_until = None
        job.locked_by = None
        add_event(s, job.id, "retry_scheduled", message, {"in_seconds": round(delay, 1), "traceback": detail})
        return True
    _finish_failed(s, job, message, "retryable" if retryable else "permanent")
    s.add(JobEvent(job_id=job.id, type="traceback", message="", data={"traceback": detail}))
    return False


def retry_now(s: Session, job: Job) -> Job:
    """Manual retry of a failed or cancelled job: fresh attempts, runs immediately."""
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise ValueError("Only failed or cancelled jobs can be retried.")
    if job.dedupe_key:
        clash = s.scalar(select(Job).where(Job.dedupe_key == job.dedupe_key, Job.status.in_(ACTIVE), Job.id != job.id))
        if clash:
            raise ValueError("The same work is already queued or running.")
    job.status = JobStatus.queued
    job.attempts = 0
    job.run_after = utcnow()
    job.finished_at = None
    job.progress = 0
    add_event(s, job.id, "retry_manual", "Retried by user")
    return job


def cancel(s: Session, job: Job) -> Job:
    """Cancel a queued or running job. A running worker notices at its next lease renewal or progress update."""
    if job.status not in ACTIVE:
        raise ValueError("Only queued or running jobs can be cancelled.")
    job.status = JobStatus.cancelled
    job.lease_until = None
    job.locked_by = None
    job.finished_at = utcnow()
    add_event(s, job.id, "cancelled", "Cancelled by user")
    return job
