"""Job handlers registry and the context a handler runs with."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..db import session_scope
from ..errors import Cancelled
from ..models import Job, JobStatus
from .queue import add_event


@dataclass
class JobContext:
    job_id: uuid.UUID
    kind: str
    payload: dict
    video_id: uuid.UUID | None
    attempt: int
    worker_id: str
    _lost: threading.Event = field(default_factory=threading.Event)
    _last_pct: int = -1
    _last_write: float = 0.0

    def lost(self) -> None:
        self._lost.set()

    def check(self) -> None:
        """Raise Cancelled if the job was cancelled or this worker lost its lease. Call it in loops."""
        if self._lost.is_set():
            raise Cancelled("Job was cancelled or reassigned.")

    def progress(self, pct: float, message: str | None = None) -> None:
        """Report progress 0-100. Cheap to call often; only writes when the whole percent changes."""
        self.check()
        p = max(0, min(100, int(pct)))
        now = time.monotonic()
        # Write when the percent changes, but also at least every 2 s so cancellation is noticed quickly.
        if p == self._last_pct and not message and now - self._last_write < 2.0:
            return
        self._last_pct = p
        self._last_write = now
        with session_scope() as s:
            res = s.execute(
                update(Job)
                .where(Job.id == self.job_id, Job.locked_by == self.worker_id, Job.status == JobStatus.running)
                .values(progress=p)
            )
            if res.rowcount != 1:
                self.lost()
            elif message:
                add_event(s, self.job_id, "progress", message, {"progress": p})
        self.check()

    def log(self, message: str, **data) -> None:
        with session_scope() as s:
            add_event(s, self.job_id, "log", message, data)


@dataclass
class Handler:
    run: Callable[[JobContext], dict | None]
    # Runs in the same transaction that marks the job succeeded (e.g. advance the video, enqueue next stage).
    on_success: Callable[[Session, Job, dict], None] | None = None
    # Runs when the job fails for good (no retries left or permanent error).
    on_failure: Callable[[Session, Job], None] | None = None


HANDLERS: dict[str, Handler] = {}


def register(kind: str, handler: Handler) -> None:
    HANDLERS[kind] = handler
