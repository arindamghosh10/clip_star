import threading
import time

from clipstar.db import session_scope
from clipstar.errors import PermanentError
from clipstar.jobs import queue
from clipstar.jobs.runtime import HANDLERS, Handler, register
from clipstar.models import Job, JobStatus
from clipstar.worker import Worker

from .conftest import drain


def _job(kind: str) -> Job:
    with session_scope() as s:
        return queue.enqueue(s, kind, {})


def _status(job_id):
    with session_scope() as s:
        return s.get(Job, job_id)


def test_success_runs_follow_up_in_same_transaction():
    calls = []
    register("t.ok", Handler(run=lambda ctx: {"n": 1}, on_success=lambda s, job, res: calls.append(res)))
    j = _job("t.ok")
    drain(Worker("w"))
    job = _status(j.id)
    assert job.status == JobStatus.succeeded and job.result == {"n": 1} and job.progress == 100
    assert calls == [{"n": 1}]


def test_flaky_job_retries_then_succeeds():
    tries = {"n": 0}

    def run(ctx):
        tries["n"] += 1
        if tries["n"] < 3:
            raise ConnectionError("temporary")
        return {}

    register("t.flaky", Handler(run=run))
    j = _job("t.flaky")
    drain(Worker("w"))
    job = _status(j.id)
    assert job.status == JobStatus.succeeded and job.attempts == 3


def test_permanent_error_fails_once_and_calls_on_failure():
    failed = []
    register("t.bad", Handler(run=lambda ctx: (_ for _ in ()).throw(PermanentError("x", user_message="Nope")), on_failure=lambda s, job: failed.append(job.id)))
    j = _job("t.bad")
    drain(Worker("w"))
    job = _status(j.id)
    assert job.status == JobStatus.failed and job.attempts == 1 and job.last_error == "Nope"
    assert failed == [j.id]


def test_unknown_kind_fails_permanently():
    j = _job("t.nobody-handles-this")
    HANDLERS.pop("t.nobody-handles-this", None)
    drain(Worker("w"))
    assert _status(j.id).status == JobStatus.failed


def test_cancel_while_running_stops_the_handler():
    started = threading.Event()

    def run(ctx):
        started.set()
        for _ in range(200):
            ctx.progress(1)  # notices cancellation
            time.sleep(0.02)
        return {}

    register("t.long", Handler(run=run))
    j = _job("t.long")
    w = Worker("w")
    t = threading.Thread(target=w.run_once)
    t.start()
    assert started.wait(5)
    with session_scope() as s:
        queue.cancel(s, s.get(Job, j.id))
    t.join(10)
    assert not t.is_alive()
    assert _status(j.id).status == JobStatus.cancelled


def test_failing_follow_up_does_not_leave_job_running():
    def boom(s, job, res):
        raise RuntimeError("follow-up broke")

    register("t.followup", Handler(run=lambda ctx: {}, on_success=boom))
    j = _job("t.followup")
    w = Worker("w")
    w.run_once()
    job = _status(j.id)
    assert job.status in (JobStatus.queued, JobStatus.failed)  # retried, never stuck in running
    assert "follow-up broke" in (job.last_error or "")
