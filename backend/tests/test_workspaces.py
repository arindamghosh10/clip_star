import pytest
from fastapi.testclient import TestClient

from clipstar.api.main import app
from clipstar.config import get_settings
from clipstar.db import session_scope
from clipstar.models import Video
from clipstar.storage import get_storage

H = {"X-ClipStar": "1"}
PW = "correct horse battery"


@pytest.fixture
def owner(client):
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": PW, "workspace_name": "Maya Money"}, headers=H)
    return client


def join(owner, email, role):
    r = owner.post("/api/users", json={"email": email, "role": role}, headers=H).json()
    if not r.get("invite_url"):
        return None
    c = TestClient(app)
    c.post("/api/auth/invite/accept", json={"token": r["invite_url"].split("token=")[1], "name": email.split("@")[0], "password": PW}, headers=H)
    return c


def test_create_switch_and_isolation(owner):
    first = owner.get("/api/workspace").json()["id"]
    owner.post("/api/accounts", json={"platform": "instagram", "handle": "@maya"}, headers=H)
    r = owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H)
    assert r.status_code == 201 and r.json()["current"]
    assert owner.get("/api/workspace").json()["name"] == "Leo Cooks"
    assert owner.get("/api/accounts").json() == []  # nothing leaks across
    owner.post("/api/accounts", json={"platform": "tiktok", "handle": "@leo"}, headers=H)
    names = {w["name"]: w for w in owner.get("/api/workspaces").json()}
    assert set(names) == {"Maya Money", "Leo Cooks"} and names["Leo Cooks"]["current"]
    assert owner.post(f"/api/workspaces/{first}/switch", headers=H).status_code == 200
    assert [a["handle"] for a in owner.get("/api/accounts").json()] == ["@maya"]
    st = owner.get("/api/auth/state").json()
    assert st["workspace"]["name"] == "Maya Money" and len(st["workspaces"]) == 2


def test_roles_are_per_workspace(owner):
    sam = join(owner, "sam@example.com", "viewer")
    owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H)
    r = owner.post("/api/users", json={"email": "sam@example.com", "role": "editor"}, headers=H).json()
    assert r["added_existing"] is True and r["invite_url"] is None  # already has a login: just added
    assert sam.post("/api/accounts", json={"platform": "x", "handle": "@s"}, headers=H).status_code == 403  # viewer in Maya Money
    leo = next(w for w in sam.get("/api/workspaces").json() if w["name"] == "Leo Cooks")
    assert leo["role"] == "editor"
    sam.post(f"/api/workspaces/{leo['id']}/switch", headers=H)
    assert sam.post("/api/accounts", json={"platform": "x", "handle": "@s"}, headers=H).status_code == 201
    # a stranger can't switch into a workspace they're not in
    outsider = join(owner, "o@example.com", "viewer")  # invited to Leo Cooks (owner's current)
    first = next(w["id"] for w in owner.get("/api/workspaces").json() if w["name"] == "Maya Money")
    assert outsider.post(f"/api/workspaces/{first}/switch", headers=H).status_code == 404
    assert sam.post("/api/workspaces", json={"name": "Mine"}, headers=H).status_code == 403  # not an owner anywhere


def test_disable_in_one_workspace_keeps_the_other(owner):
    sam = join(owner, "sam@example.com", "editor")
    first = owner.get("/api/workspace").json()["id"]
    owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H)
    owner.post("/api/users", json={"email": "sam@example.com", "role": "viewer"}, headers=H)
    owner.post(f"/api/workspaces/{first}/switch", headers=H)
    sid = next(u["id"] for u in owner.get("/api/users").json() if u["email"] == "sam@example.com")
    owner.patch(f"/api/users/{sid}", json={"disabled": True}, headers=H)
    assert sam.get("/api/workspace").json()["name"] == "Leo Cooks"  # falls back to where they still have access
    assert [w["name"] for w in sam.get("/api/workspaces").json()] == ["Leo Cooks"]
    # removed from the last one: no access at all
    leo = next(w["id"] for w in owner.get("/api/workspaces").json() if w["name"] == "Leo Cooks")
    owner.post(f"/api/workspaces/{leo}/switch", headers=H)
    assert owner.delete(f"/api/users/{sid}", headers=H).status_code == 204
    assert sam.get("/api/videos").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"email": "sam@example.com", "password": PW}, headers=H).status_code == 401


def test_keys_and_token_pick_their_workspace(owner, monkeypatch):
    first = owner.get("/api/workspace").json()["id"]
    k1 = owner.post("/api/keys", json={"name": "k", "role": "editor"}, headers=H).json()["key"]
    second = owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H).json()["id"]
    bot = TestClient(app)
    assert bot.get("/api/workspace", headers={"Authorization": f"Bearer {k1}"}).json()["id"] == first
    assert bot.post(f"/api/workspaces/{second}/switch", headers={"Authorization": f"Bearer {k1}"}).status_code == 403
    monkeypatch.setattr(get_settings(), "api_token", "tok")
    t = {"Authorization": "Bearer tok"}
    assert bot.get("/api/workspace", headers=t).json()["id"] == first
    assert bot.get("/api/workspace", headers={**t, "X-ClipStar-Workspace": second}).json()["id"] == second
    assert bot.get("/api/workspace", headers={**t, "X-ClipStar-Workspace": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_delete_workspace(owner):
    first = owner.get("/api/workspace").json()["id"]
    assert owner.request("DELETE", f"/api/workspaces/{first}", json={"confirm_name": "Maya Money"}, headers=H).status_code == 409  # the only one
    second = owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H).json()["id"]
    with session_scope() as s:
        v = Video(workspace_id=second, title="x", source_filename="x.mp4")
        s.add(v)
        s.flush()
        vid = v.id
    p = get_storage().abs(f"videos/{vid}/master.mp4")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    assert owner.request("DELETE", f"/api/workspaces/{second}", json={"confirm_name": "leo"}, headers=H).status_code == 422
    assert owner.request("DELETE", f"/api/workspaces/{second}", json={"confirm_name": "Leo Cooks"}, headers=H).status_code == 204
    assert not p.exists()
    assert owner.get("/api/workspace").json()["id"] == first  # session falls back
    assert [w["name"] for w in owner.get("/api/workspaces").json()] == ["Maya Money"]


def test_backups_are_for_the_server_admin_only(owner, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_dir", tmp_path)
    (tmp_path / "clipstar-backup-20261101-000000.tar.gz").write_bytes(b"x")
    assert owner.get("/api/admin/backups").status_code == 200  # setup person = admin
    leo_owner = join(owner, "leo@example.com", "owner")  # owner of a workspace, but not the server admin
    assert leo_owner.get("/api/admin/backups").status_code == 403
    assert leo_owner.get("/api/admin/backups/clipstar-backup-20261101-000000.tar.gz").status_code == 403
    assert leo_owner.post("/api/admin/storage/clean", headers=H).status_code == 403
    assert leo_owner.put("/api/admin/budget", json={"monthly_budget_usd": 3}, headers=H).status_code == 200  # workspace owner things still fine


def test_notification_settings_are_per_workspace(owner):
    owner.patch("/api/auth/me", json={"email_notifications": False}, headers=H)
    owner.post("/api/workspaces", json={"name": "Leo Cooks"}, headers=H)
    assert owner.get("/api/auth/me").json()["user"]["prefs"]["email"] is True
