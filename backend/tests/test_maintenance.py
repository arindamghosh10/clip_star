import os
import subprocess
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text, update

from clipstar import backup, maintenance
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.models import Asset, Clip, ClipStatus, Job, JobStatus, Notification, Video, VideoStatus, Workspace
from clipstar.pipeline import register_all
from clipstar.storage import get_storage
from clipstar.worker import Worker

from .conftest import drain

H = {"X-ClipStar": "1"}


@pytest.fixture(autouse=True)
def _setup(client):
    register_all()
    client.get("/api/workspace")


def write(rel: str, size: int = 1000) -> str:
    p = get_storage().abs(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return rel


def make_video(days_old: int = 0, clip_status=ClipStatus.approved):
    with session_scope() as s:
        ws = s.query(Workspace).one()
        v = Video(workspace_id=ws.id, title="Ep", source_filename="a.mp4", status=VideoStatus.ready)
        s.add(v)
        s.flush()
        v.created_at = maintenance.now() - timedelta(days=days_old)
        d = f"videos/{v.id}"
        for kind, name in (("master", "master.mp4"), ("proxy", "proxy.mp4"), ("audio", "audio.wav"), ("transcript", "transcript.json")):
            s.add(Asset(video_id=v.id, kind=kind, path=write(f"{d}/{name}"), size_bytes=1000))
        c = Clip(video_id=v.id, title="C", start_s=0, end_s=30, score=60, status=clip_status, meta={"renders": {"A": {"path": write(f"{d}/clips/c/A.mp4"), "cover": write(f"{d}/clips/c/A.jpg", 10)}}})
        s.add(c)
        s.flush()
        return v.id, c.id


def test_audio_deleted_rejected_renders_kept_for_a_week(client):
    vid, cid = make_video(clip_status=ClipStatus.rejected)
    maintenance.run()
    with session_scope() as s:
        kinds = set(s.scalars(select(Asset.kind).where(Asset.video_id == vid)))
        assert kinds == {"master", "proxy", "transcript"}
        assert s.get(Clip, cid).meta["renders"]  # rejected today: kept for now
        s.execute(update(Clip).where(Clip.id == cid).values(updated_at=maintenance.now() - timedelta(days=8)))
    maintenance.run()
    with session_scope() as s:
        assert s.get(Clip, cid).meta["renders"] == {}
    assert not get_storage().abs(f"videos/{vid}/clips/c/A.mp4").exists()
    assert not get_storage().abs(f"videos/{vid}/audio.wav").exists()


def test_archiving_is_off_by_default_and_respects_waiting_work(client):
    vid, cid = make_video(days_old=40)
    maintenance.run()
    with session_scope() as s:
        assert not (s.get(Video, vid).meta or {}).get("archived")
    r = client.put("/api/admin/storage", json={"archive_after_days": 30, "rejected_render_days": 7, "delete_audio": True}, headers=H)
    assert r.status_code == 200 and r.json()["policy"]["archive_after_days"] == 30
    # a pending clip blocks archiving
    with session_scope() as s:
        s.add(Clip(video_id=vid, title="P", start_s=0, end_s=20, score=50, status=ClipStatus.pending))
    maintenance.run()
    with session_scope() as s:
        assert not (s.get(Video, vid).meta or {}).get("archived")
        for c in s.scalars(select(Clip).where(Clip.video_id == vid, Clip.status == ClipStatus.pending)):
            c.status = ClipStatus.rejected
    maintenance.run()
    with session_scope() as s:
        assert (s.get(Video, vid).meta or {}).get("archived")
        assert set(s.scalars(select(Asset.kind).where(Asset.video_id == vid))) == {"transcript"}
        assert s.get(Clip, cid).meta["renders"]["A"]  # approved clip renders stay
    assert not get_storage().abs(f"videos/{vid}/master.mp4").exists()
    assert client.post(f"/api/videos/{vid}/reclip", headers=H).status_code == 409
    assert client.post(f"/api/clips/{cid}/render", headers=H).status_code == 409
    assert client.patch(f"/api/clips/{cid}", json={"title": "Still editable"}, headers=H).status_code == 200


def test_busy_videos_are_never_touched(client):
    vid, _ = make_video()
    with session_scope() as s:
        s.add(Job(kind="pipeline.stage", payload={"stage": "edit"}, video_id=vid, status=JobStatus.queued))
    maintenance.run()
    assert get_storage().abs(f"videos/{vid}/audio.wav").exists()


def test_purge_and_temp_files_and_dispatch(client):
    with session_scope() as s:
        j = Job(kind="x", payload={}, status=JobStatus.succeeded)
        s.add(j)
        s.flush()
        j.finished_at = maintenance.now() - timedelta(days=40)
    tmp = get_storage().abs("videos/.tmp-old.mp4")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(b"x")
    os.utime(tmp, (0, 0))
    res = maintenance.run()
    assert res["purged"]["jobs"] == 1 and res["temp_files"] == 1
    assert maintenance.dispatch_maintenance() is True
    drain(Worker("w"), limit=3)
    assert maintenance.dispatch_maintenance() is False  # ran today


def test_low_disk_notifies(client, monkeypatch):
    monkeypatch.setattr(type(get_storage()), "free_bytes", lambda self: 1024**3)
    maintenance.run()
    maintenance.run()
    with session_scope() as s:
        assert [n.title for n in s.scalars(select(Notification).where(Notification.kind == "storage"))] == ["Disk space is low (1.0 GB free)"]
    u = client.get("/api/admin/storage").json()
    assert u["free_bytes"] == 1024**3 and "originals" in u["by_kind"]


# ---------- backups ----------

pytestmark_pg = pytest.mark.skipif(subprocess.run(["which", "pg_dump"], capture_output=True).returncode != 0, reason="pg_dump not installed")


@pytestmark_pg
def test_backup_and_restore_roundtrip(client, tmp_path, monkeypatch):
    st = get_settings()
    # restore into a scratch database so the test database isn't replaced underneath the other tests
    admin = create_engine(st.database_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS clipstar_restore_test"))
        c.execute(text("CREATE DATABASE clipstar_restore_test"))
    monkeypatch.setattr(st, "backup_dir", tmp_path)
    client.patch("/api/workspace", json={"name": "Before backup"}, headers=H)
    vid, _ = make_video()
    from clipstar.secrets import current_key

    key = current_key()
    p = backup.create(media=True)
    assert backup.NAME_RE.match(p.name) and oct(p.stat().st_mode)[-3:] == "600"
    with tarfile.open(p) as t:
        names = t.getnames()
    assert {"manifest.json", "database.dump", "secret_key"} <= set(names) and any(n.startswith("media/videos/") for n in names)
    assert [b["name"] for b in backup.list_backups()] == [p.name]

    monkeypatch.setattr(st, "database_url", st.database_url.rsplit("/", 1)[0] + "/clipstar_restore_test")
    restored_dir = tmp_path / "restored"
    monkeypatch.setattr(st, "storage_dir", restored_dir)
    monkeypatch.setattr(st, "secret_key", None)
    res = backup.restore(p)
    assert res["media"] and (restored_dir / ".secret_key").read_text() == key
    eng = create_engine(st.database_url)
    with eng.connect() as c:
        assert c.execute(text("select name from workspaces")).scalar() == "Before backup"
    eng.dispose()
    assert (restored_dir / "videos" / str(vid) / "master.mp4").exists()
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS clipstar_restore_test WITH (FORCE)"))


def test_backup_prune_and_names(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_dir", tmp_path)
    for i in range(4):
        (tmp_path / f"clipstar-backup-2026110{i}-000000.tar.gz").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("keep me")
    assert backup.prune(2) == 2
    assert [b["name"] for b in backup.list_backups()] == ["clipstar-backup-20261103-000000.tar.gz", "clipstar-backup-20261102-000000.tar.gz"]
    assert (tmp_path / "notes.txt").exists()
    with pytest.raises(ValueError):
        backup.path_of("../../etc/passwd")


def test_restore_refuses_unsafe_paths(tmp_path):
    bad = tmp_path / "clipstar-backup-20261101-000000.tar.gz"
    evil = tmp_path / "evil"
    evil.write_text("x")
    with tarfile.open(bad, "w:gz") as t:
        t.add(evil, arcname="../evil")
    from clipstar.errors import PermanentError

    with pytest.raises(PermanentError) as e:
        backup.restore(bad)
    assert "unsafe path" in e.value.user_message


def test_backup_api_owner_only(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_dir", tmp_path)
    (tmp_path / "clipstar-backup-20261101-000000.tar.gz").write_bytes(b"x")
    assert client.get("/api/admin/backups").json()["items"][0]["name"] == "clipstar-backup-20261101-000000.tar.gz"
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    assert client.get("/api/admin/backups/clipstar-backup-20261101-000000.tar.gz").status_code == 200
    tok = client.post("/api/users", json={"email": "e@example.com", "role": "editor"}, headers=H).json()["invite_url"].split("token=")[1]
    from fastapi.testclient import TestClient

    from clipstar.api.main import app

    e = TestClient(app)
    e.post("/api/auth/invite/accept", json={"token": tok, "name": "E", "password": "correct horse battery"}, headers=H)
    assert e.get("/api/admin/backups/clipstar-backup-20261101-000000.tar.gz").status_code == 403
    assert e.post("/api/admin/backups", json={}, headers=H).status_code == 403
    assert client.get("/api/admin/backups/nope.tar.gz").status_code == 404
