from sqlalchemy import select

from clipstar import upload_alerts
from clipstar.db import session_scope
from clipstar.models import Account, Event, Notification, Workspace
from clipstar.pipeline import register_all
from clipstar.platforms.youtube import YouTube
from clipstar.worker import Worker

from .conftest import drain


def test_new_uploads_are_announced_once(client, monkeypatch):
    register_all()
    client.get("/api/workspace")
    with session_scope() as s:
        ws = s.query(Workspace).one()
        a = Account(workspace_id=ws.id, platform="youtube", handle="Maya Money", connection="oauth", remote_id="chan1")
        s.add(a)
        s.flush()
        aid = a.id
    feed = [[{"id": "old1", "title": "Old", "published_at": "2026-11-01T00:00:00Z"}]]
    monkeypatch.setattr("clipstar.publishing.service.fresh_tokens", lambda aid: (None, None))
    monkeypatch.setattr(YouTube, "latest_uploads", lambda self, app, tok, rid, limit=5: feed[0])

    def check():
        with session_scope() as s:
            acc = s.get(Account, aid)
            acc.options = {**(acc.options or {}), "uploads_checked_at": None}
            acc.options = {k: v for k, v in acc.options.items() if v is not None}
        assert upload_alerts.dispatch() == 1
        drain(Worker("w"), limit=2)

    check()  # first look: baseline only
    with session_scope() as s:
        assert s.scalar(select(Notification.id)) is None
    feed[0] = [{"id": "new2", "title": "Rent mistakes (full episode)", "published_at": "2026-11-07T00:00:00Z"}] + feed[0]
    check()
    check()  # nothing new the second time
    with session_scope() as s:
        titles = [n.title for n in s.scalars(select(Notification))]
        assert titles == ["New on YouTube: Rent mistakes (full episode)"]
        ev = s.scalar(select(Event).where(Event.type == "youtube.new_upload"))
        assert ev.data["url"].endswith("v=new2")
    # recently checked accounts aren't checked again within the hour
    assert upload_alerts.dispatch() == 0
