"""Worker process: claims jobs and runs them. Start with `python -m clipstar.worker`.

Run as many workers as you like (on one or many machines); the queue keeps them from colliding.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid

from sqlalchemy.dialects.postgresql import insert

from .config import get_settings
from .db import new_session, session_scope
from .errors import Cancelled, PermanentError
from .jobs import queue
from .jobs.runtime import HANDLERS, JobContext
from .models import Job, WorkerHeartbeat

log = logging.getLogger("clipstar.worker")


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.settings = get_settings()
        self._stop = threading.Event()

    # ----- lifecycle -----

    def stop(self, *_):
        log.info("stopping after current job")
        self._stop.set()

    def _beat(self, current: uuid.UUID | None = None) -> None:
        try:
            with session_scope() as s:
                stmt = insert(WorkerHeartbeat).values(id=self.id, hostname=socket.gethostname(), current_job=current)
                s.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[WorkerHeartbeat.id],
                        set_={"last_seen": queue.utcnow(), "current_job": current},
                    )
                )
        except Exception:  # heartbeat problems must never kill the worker
            log.exception("heartbeat failed")

    def run_forever(self) -> None:
        from .pipeline import register_all  # noqa: F401  (registers handlers)

        register_all()
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        log.info("worker %s started", self.id)
        last_beat = 0.0
        last_dispatch = 0.0
        while not self._stop.is_set():
            if time.monotonic() - last_beat > 15:
                self._beat()
                last_beat = time.monotonic()
            if time.monotonic() - last_dispatch > self.settings.publish_check_seconds:
                last_dispatch = time.monotonic()
                try:
                    from .publishing.service import dispatch

                    dispatch()
                except Exception:
                    log.exception("publish dispatch failed")
            try:
                ran = self.run_once()
            except Exception:
                # Database down or similar: back off and keep going.
                log.exception("worker loop error")
                self._stop.wait(5)
                continue
            if not ran:
                self._stop.wait(self.settings.worker_poll_seconds)
        log.info("worker %s stopped", self.id)

    # ----- one job -----

    def run_once(self) -> bool:
        s = new_session()
        try:
            job = queue.claim(s, self.id)
        finally:
            s.close()
        if job is None:
            return False
        self.execute(job)
        return True

    def execute(self, job: Job) -> None:
        ctx = JobContext(job_id=job.id, kind=job.kind, payload=dict(job.payload), video_id=job.video_id, attempt=job.attempts, worker_id=self.id)
        handler = HANDLERS.get(job.kind)
        self._beat(job.id)

        stop_hb = threading.Event()

        def heartbeat():
            interval = max(5, self.settings.worker_lease_seconds // 3)
            while not stop_hb.wait(interval):
                try:
                    s = new_session()
                    try:
                        if not queue.renew_lease(s, job.id, self.id):
                            ctx.lost()
                            return
                    finally:
                        s.close()
                except Exception:
                    log.exception("lease renewal failed")

        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()
        result: dict | None = None
        error: BaseException | None = None
        try:
            if handler is None:
                raise PermanentError(f"No handler for job kind '{job.kind}'.")
            result = handler.run(ctx) or {}
        except BaseException as e:  # noqa: BLE001 - we record every failure
            error = e
        finally:
            stop_hb.set()
            hb.join(timeout=5)

        self._finish(job.id, handler, result, error)
        self._beat(None)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise error

    def _finish(self, job_id, handler, result, error) -> None:
        try:
            self._finish_tx(job_id, handler, result, error)
        except Exception as e:
            # The follow-up step itself failed (e.g. a DB constraint). Record it as a job failure
            # in a fresh transaction so the job never sits in "running" with a dead outcome.
            log.exception("finishing job %s failed", job_id)
            with session_scope() as s:
                job = queue.lock_owned(s, job_id, self.id)
                if job is not None:
                    if not queue.mark_failed(s, job, e) and handler and handler.on_failure:
                        handler.on_failure(s, job)

    def _finish_tx(self, job_id, handler, result, error) -> None:
        with session_scope() as s:
            job = queue.lock_owned(s, job_id, self.id)
            if job is None:
                # Cancelled or reassigned while running: someone else owns the outcome now.
                log.info("job %s no longer owned; result discarded", job_id)
                return
            if error is None:
                queue.mark_succeeded(s, job, result)
                if handler and handler.on_success:
                    handler.on_success(s, job, result or {})
                return
            if isinstance(error, Cancelled):
                job.status = queue.JobStatus.cancelled
                job.locked_by = None
                job.lease_until = None
                job.finished_at = queue.utcnow()
                queue.add_event(s, job.id, "cancelled", str(error))
                return
            will_retry = queue.mark_failed(s, job, error)
            log.warning("job %s %s: %s", job_id, "will retry" if will_retry else "failed", error)
            if not will_retry and handler and handler.on_failure:
                handler.on_failure(s, job)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Worker().run_forever()


if __name__ == "__main__":
    main()
