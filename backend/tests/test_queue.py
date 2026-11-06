import threading
from datetime import timedelta

from sqlalchemy import update

from clipstar.db import new_session, session_scope
from clipstar.errors import PermanentError, RetryableError
from clipstar.jobs import queue
from clipstar.models import Job, JobStatus


def _enqueue(**kw) -> Job:
    with session_scope() as s:
        return queue.enqueue(s, "test.kind", {"x": 1}, **kw)


def _claim(worker="w1", lease=None):
    s = new_session()
    try:
        return queue.claim(s, worker, lease)
    finally:
        s.close()


def test_dedupe_returns_active_job():
    a = _enqueue(dedupe_key="k1")
    b = _enqueue(dedupe_key="k1")
    assert a.id == b.id
    c = _enqueue(dedupe_key="k2")
    assert c.id != a.id


def test_dedupe_allows_new_job_after_finish():
    a = _enqueue(dedupe_key="k1")
    with session_scope() as s:
        s.execute(update(Job).where(Job.id == a.id).values(status=JobStatus.succeeded))
    b = _enqueue(dedupe_key="k1")
    assert b.id != a.id


def test_claim_once_only():
    _enqueue()
    assert _claim("w1") is not None
    assert _claim("w2") is None


def test_concurrent_claims_never_share_a_job():
    for _ in range(20):
        _enqueue()
    got: list = []
    lock = threading.Lock()

    def worker(name):
        while True:
            j = _claim(name)
            if j is None:
                return
            with lock:
                got.append(j.id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 20 and len(set(got)) == 20


def test_retryable_failure_backs_off_then_permanent_stops():
    j = _enqueue()
    job = _claim()
    with session_scope() as s:
        job = queue.lock_owned(s, j.id, "w1")
        assert queue.mark_failed(s, job, RetryableError("net down")) is True
    with session_scope() as s:
        job = s.get(Job, j.id)
        assert job.status == JobStatus.queued and job.attempts == 1 and job.last_error == "net down"
    import time

    time.sleep(0.1)
    job = _claim()
    assert job is not None and job.attempts == 2
    with session_scope() as s:
        job = queue.lock_owned(s, j.id, "w1")
        assert queue.mark_failed(s, job, PermanentError("bad", user_message="Bad file")) is False
    with session_scope() as s:
        job = s.get(Job, j.id)
        assert job.status == JobStatus.failed and job.error_kind == "permanent" and job.last_error == "Bad file"


def test_retries_stop_at_max_attempts():
    j = _enqueue(max_attempts=2)
    for attempt in (1, 2):
        import time

        time.sleep(0.1)
        assert _claim() is not None
        with session_scope() as s:
            job = queue.lock_owned(s, j.id, "w1")
            will_retry = queue.mark_failed(s, job, RuntimeError("boom"))
        assert will_retry is (attempt < 2)
    with session_scope() as s:
        assert s.get(Job, j.id).status == JobStatus.failed


def test_crashed_worker_job_is_reclaimed_and_old_owner_is_fenced():
    j = _enqueue()
    assert _claim("dead-worker") is not None
    # simulate the dead worker's lease running out
    with session_scope() as s:
        s.execute(update(Job).where(Job.id == j.id).values(lease_until=queue.utcnow() - timedelta(seconds=1)))
    job = _claim("w2")
    assert job is not None and job.id == j.id and job.attempts == 2 and job.locked_by == "w2"
    s = new_session()
    try:
        assert queue.renew_lease(s, j.id, "dead-worker") is False
        assert queue.lock_owned(s, j.id, "dead-worker") is None
    finally:
        s.close()


def test_reclaim_after_too_many_crashes_fails_the_job():
    j = _enqueue(max_attempts=1)
    assert _claim("a") is not None
    with session_scope() as s:
        s.execute(update(Job).where(Job.id == j.id).values(lease_until=queue.utcnow() - timedelta(seconds=1)))
    assert _claim("b") is None
    with session_scope() as s:
        job = s.get(Job, j.id)
        assert job.status == JobStatus.failed and "too many times" in job.last_error


def test_cancel_and_manual_retry():
    j = _enqueue(dedupe_key="v:1")
    with session_scope() as s:
        queue.cancel(s, s.get(Job, j.id))
    assert _claim() is None
    with session_scope() as s:
        job = queue.retry_now(s, s.get(Job, j.id))
        assert job.status == JobStatus.queued and job.attempts == 0
    assert _claim() is not None
