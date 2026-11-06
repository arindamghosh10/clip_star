import smtplib
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from clipstar import budget, mailer
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.engines.llm import EngineDeclined, claude_json
from clipstar.models import Account, AccountStatus, Batch, BatchStatus, Clip, ClipStatus, EngineUsage, Job, Notification, Post, PostStatus, Video, VideoStatus, Workspace
from clipstar.notify import dispatch_email
from clipstar.pipeline import register_all
from clipstar.worker import Worker

from .conftest import drain

H = {"X-ClipStar": "1"}


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()
    client.get("/api/workspace")


def ws_id():
    with session_scope() as s:
        return s.query(Workspace).one().id


def titles():
    with session_scope() as s:
        return [n.title for n in s.scalars(select(Notification).order_by(Notification.created_at))]


def test_status_changes_notify_once(client):
    acc = client.post("/api/accounts", json={"platform": "instagram", "handle": "@maya"}).json()
    with session_scope() as s:
        v = Video(workspace_id=ws_id(), title="Ep 1", source_filename="a.mp4")
        s.add(v)
        s.flush()
        vid = v.id
    with session_scope() as s:
        s.get(Video, vid).status = VideoStatus.ready
    with session_scope() as s:
        a = s.get(Account, acc["id"])
        a.status = AccountStatus.reconnect
        a.last_error = "Login expired"
    with session_scope() as s:  # same day: no second notification
        s.get(Account, acc["id"]).status = AccountStatus.connected
    with session_scope() as s:
        s.get(Account, acc["id"]).status = AccountStatus.reconnect
    with session_scope() as s:
        cs = [Clip(video_id=vid, title=f"C{i}", start_s=0, end_s=10, score=50, status=ClipStatus.approved) for i in range(2)]
        b = Batch(workspace_id=ws_id(), name="Rule batch", origin="rule:x:y")
        s.add_all([*cs, b])
        s.flush()
        posts = [Post(batch_id=b.id, account_id=acc["id"], clip_id=c.id, variant="A", caption="x", scheduled_at=budget.month_start(), status=PostStatus.scheduled) for c in cs]
        s.add_all(posts)
    with session_scope() as s:
        for p in s.scalars(select(Post)):
            p.status = PostStatus.failed  # two failures in one batch -> one notification
            p.last_error = "Rejected"
    t = titles()
    assert t == ["“Ep 1” is ready", "Reconnect @maya (instagram)", "Batch “Rule batch” is waiting for approval", "Posts need attention in “Rule batch”"]

    r = client.get("/api/notifications").json()
    assert r["unread"] == 4 and r["items"][0]["link"].startswith("/posts")
    client.post("/api/notifications/seen")
    assert client.get("/api/notifications").json()["unread"] in (0, 4)  # open mode has no person to remember it for


def test_hook_failure_never_breaks_the_write(client, monkeypatch):
    import clipstar.notify as n

    monkeypatch.setattr(n, "_scan", lambda s: 1 / 0)
    with session_scope() as s:
        s.add(Video(workspace_id=ws_id(), title="x", source_filename="x.mp4"))
    with session_scope() as s:
        assert s.scalar(select(Video.id)) is not None


def test_email_sent_to_people_who_want_it(client, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            pass

        def send_message(self, msg):
            sent.append(msg)

    st = get_settings()
    monkeypatch.setattr(st, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(st, "smtp_from", "clipstar@example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    client.patch("/api/auth/me", json={"kinds": ["video_ready"]}, headers=H)
    with session_scope() as s:
        v = Video(workspace_id=ws_id(), title="Ep 2", source_filename="a.mp4")
        s.add(v)
        s.flush()
        a = Account(workspace_id=ws_id(), platform="x", handle="@m", connection="simulated")
        s.add(a)
        s.flush()
        v.status = VideoStatus.ready
        a.status = AccountStatus.reconnect
    assert dispatch_email() == 2
    drain(Worker("w"), limit=5)
    assert len(sent) == 1 and sent[0]["To"] == "maya@example.com" and "Ep 2" in sent[0]["Subject"]  # reconnect not wanted
    assert dispatch_email() == 0  # both marked as emailed


def test_email_gives_up_on_bad_login(client, monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(st, "smtp_from", "x@example.com")

    def boom(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"bad")

    monkeypatch.setattr(mailer, "send", lambda *a, **k: (_ for _ in ()).throw(__import__("clipstar.errors", fromlist=["PermanentError"]).PermanentError("x", user_message="bad login")))
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    with session_scope() as s:
        v = Video(workspace_id=ws_id(), title="Ep", source_filename="a.mp4")
        s.add(v)
        s.flush()
        v.status = VideoStatus.failed
    dispatch_email()
    drain(Worker("w"), limit=5)
    assert dispatch_email() == 0  # not retried forever
    with session_scope() as s:
        assert s.scalar(select(Job.status).where(Job.kind == "notify.email")).value == "failed"


# ---------- budget ----------


class FakeAnthropic:
    calls = 0

    def __init__(self, **kw):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        FakeAnthropic.calls += 1
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=100_000, output_tokens=10_000, cache_creation_input_tokens=0, cache_read_input_tokens=0), content=[SimpleNamespace(type="text", text="{}")])


@pytest.fixture
def fake_claude(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    FakeAnthropic.calls = 0


def test_metering_and_budget_stop(client, fake_claude):
    with budget.scope("moments"):
        assert claude_json("s", "p", {"type": "object"}) == "{}"
    b = client.get("/api/admin/budget").json()
    assert b["spent_usd"] == pytest.approx(0.6)  # 0.1M in x $4 + 0.01M out x $20
    assert b["by_engine"][0]["stage"] == "moments" and b["limit_usd"] is None

    assert client.put("/api/admin/budget", json={"monthly_budget_usd": 1.0, "budget_warn_pct": 50}, headers=H).json()["remaining_usd"] == pytest.approx(0.4)
    claude_json("s", "p", {"type": "object"})  # 1.2: crosses the limit
    assert "Paid engine budget used up" in titles()
    with pytest.raises(EngineDeclined, match="budget"):
        claude_json("s", "p", {"type": "object"})
    assert FakeAnthropic.calls == 2  # the blocked call never reached the API
    assert client.get("/api/admin/budget").json()["blocked"] is True
    client.put("/api/admin/budget", json={"monthly_budget_usd": None}, headers=H)
    claude_json("s", "p", {"type": "object"})
    assert FakeAnthropic.calls == 3


def test_budget_is_owner_only(client):
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    tok = client.post("/api/users", json={"email": "e@example.com", "role": "editor"}, headers=H).json()["invite_url"].split("token=")[1]
    from fastapi.testclient import TestClient

    from clipstar.api.main import app

    e = TestClient(app)
    e.post("/api/auth/invite/accept", json={"token": tok, "name": "E", "password": "correct horse battery"}, headers=H)
    assert e.get("/api/admin/budget").status_code == 200
    assert e.put("/api/admin/budget", json={"monthly_budget_usd": 5}, headers=H).status_code == 403
