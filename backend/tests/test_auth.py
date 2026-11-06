from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipstar import auth
from clipstar.api.main import app
from clipstar.db import session_scope
from clipstar.models import Role, User, UserSession

H = {"X-ClipStar": "1"}
PW = "correct horse battery"


def setup_owner(client):
    r = client.post("/api/auth/setup", json={"name": "Maya", "email": "Maya@Example.com", "password": PW, "workspace_name": "Maya Money"}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def test_password_hashing():
    h = auth.hash_password("abcdefghijk")
    assert h.startswith("scrypt$") and auth.verify_password("abcdefghijk", h)
    assert not auth.verify_password("abcdefghijx", h)
    assert not auth.verify_password("x", None) and not auth.verify_password("x", "garbage")
    assert auth.hash_password("abcdefghijk") != h  # salted
    assert auth.password_problem("short") and auth.password_problem("password12") and not auth.password_problem(PW)


def test_open_until_setup_then_sign_in_required(client):
    st = client.get("/api/auth/state").json()
    assert st["setup_required"] and st["user"] is None
    assert client.get("/api/videos").status_code == 200  # open during first run
    owner = setup_owner(client)
    assert owner["role"] == "owner" and owner["email"] == "maya@example.com"
    assert client.get("/api/workspace").json()["name"] == "Maya Money"
    assert client.get("/api/auth/state").json()["user"]["email"] == "maya@example.com"
    # setup can't run twice
    assert client.post("/api/auth/setup", json={"name": "X", "email": "x@y.zz", "password": PW, "workspace_name": "W"}, headers=H).status_code == 409
    # a stranger without the cookie is locked out now
    other = TestClient(app)
    assert other.get("/api/videos").status_code == 401
    assert other.get("/api/auth/state").json()["setup_required"] is False


def test_login_logout_lockout_and_csrf(client):
    setup_owner(client)
    client.post("/api/auth/logout")
    assert client.get("/api/videos").status_code == 401
    assert client.post("/api/auth/login", json={"email": "maya@example.com", "password": PW}).status_code == 403  # header missing
    for _ in range(4):
        assert client.post("/api/auth/login", json={"email": "maya@example.com", "password": "nope"}, headers=H).status_code == 401
    assert client.post("/api/auth/login", json={"email": " MAYA@example.com ", "password": PW}, headers=H).status_code == 200
    assert client.get("/api/videos").status_code == 200
    # unsafe requests from the browser session need the header (simple CSRF guard)
    assert client.patch("/api/workspace", json={"name": "New"}).status_code == 403
    assert client.patch("/api/workspace", json={"name": "New"}, headers=H).status_code == 200
    client.post("/api/auth/logout")
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "maya@example.com", "password": "nope"}, headers=H)
    r = client.post("/api/auth/login", json={"email": "maya@example.com", "password": PW}, headers=H)
    assert r.status_code == 429 and "Try again" in r.json()["detail"]
    assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": PW}, headers=H).status_code == 401


def test_sessions_expire_and_are_stored_hashed(client):
    setup_owner(client)
    raw = client.cookies.get(auth.COOKIE)
    with session_scope() as s:
        sess = s.scalar(select(UserSession))
        assert sess.token_hash == auth.token_hash(raw) and raw not in sess.token_hash
        sess.expires_at = auth.now() - timedelta(seconds=1)
    assert client.get("/api/videos").status_code == 401


def invite(client, email, role):
    r = client.post("/api/users", json={"email": email, "role": role}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["invite_url"].split("token=")[1]


def member(token, name="Sam"):
    c = TestClient(app)
    info = c.get(f"/api/auth/invite/{token}").json()
    assert info["workspace"] == "Maya Money"
    assert c.post("/api/auth/invite/accept", json={"token": token, "name": name, "password": "short"}, headers=H).status_code == 422
    r = c.post("/api/auth/invite/accept", json={"token": token, "name": name, "password": PW}, headers=H)
    assert r.status_code == 200, r.text
    assert c.get(f"/api/auth/invite/{token}").status_code == 404  # used up
    return c


def test_roles(client):
    setup_owner(client)
    assert client.post("/api/users", json={"email": "maya@example.com"}, headers=H).status_code == 409
    viewer = member(invite(client, "v@example.com", "viewer"))
    reviewer = member(invite(client, "r@example.com", "reviewer"))
    editor = member(invite(client, "e@example.com", "editor"))

    assert viewer.get("/api/videos").status_code == 200
    r = viewer.patch("/api/workspace", json={"name": "x"}, headers=H)
    assert r.status_code == 403 and "Viewer" in r.json()["detail"]
    assert viewer.patch("/api/auth/me", json={"name": "Vee"}, headers=H).json()["name"] == "Vee"  # own profile is fine

    assert reviewer.post("/api/accounts", json={"platform": "instagram", "handle": "@a"}, headers=H).status_code == 403
    assert reviewer.patch("/api/clips/00000000-0000-0000-0000-000000000000", json={"status": "approved"}, headers=H).status_code == 404  # allowed, just missing
    assert reviewer.post("/api/batches/00000000-0000-0000-0000-000000000000/approve", headers=H).status_code == 404

    assert editor.post("/api/accounts", json={"platform": "instagram", "handle": "@a"}, headers=H).status_code == 201
    assert editor.post("/api/users", json={"email": "z@example.com"}, headers=H).status_code == 403
    assert editor.put("/api/platforms/youtube/app", json={"client_id": "a", "client_secret": "b"}, headers=H).status_code == 403
    assert editor.get("/api/users").status_code == 200  # can see the team


def test_owner_guard_and_disable(client):
    me = setup_owner(client)
    r = client.patch(f"/api/users/{me['id']}", json={"role": "editor"}, headers=H)
    assert r.status_code == 409 and "at least one active owner" in r.json()["detail"]
    assert client.delete(f"/api/users/{me['id']}", headers=H).status_code == 409
    e = member(invite(client, "e@example.com", "editor"))
    users = {u["email"]: u for u in client.get("/api/users").json()}
    eid = users["e@example.com"]["id"]
    assert client.patch(f"/api/users/{eid}", json={"disabled": True}, headers=H).status_code == 200
    assert e.get("/api/videos").status_code == 401  # signed out everywhere
    assert e.post("/api/auth/login", json={"email": "e@example.com", "password": PW}, headers=H).status_code == 401
    client.patch(f"/api/users/{eid}", json={"disabled": False, "role": "owner"}, headers=H)
    assert client.patch(f"/api/users/{me['id']}", json={"role": "editor"}, headers=H).status_code == 200  # another owner exists now


def test_change_password_signs_out_other_devices(client):
    setup_owner(client)
    other = TestClient(app)
    other.post("/api/auth/login", json={"email": "maya@example.com", "password": PW}, headers=H)
    assert other.get("/api/videos").status_code == 200
    assert client.patch("/api/auth/me", json={"current_password": "wrong", "new_password": "another good one"}, headers=H).status_code == 403
    assert client.patch("/api/auth/me", json={"current_password": PW, "new_password": "another good one"}, headers=H).status_code == 200
    assert client.get("/api/videos").status_code == 200
    assert other.get("/api/videos").status_code == 401


def test_api_token_keeps_working(client, monkeypatch):
    setup_owner(client)
    from clipstar.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "s3cret")
    bot = TestClient(app)
    assert bot.get("/api/videos").status_code == 401
    assert bot.get("/api/videos", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert bot.post("/api/accounts", json={"platform": "x", "handle": "@bot"}, headers={"Authorization": "Bearer s3cret"}).status_code == 201  # no CSRF header needed


def test_expired_invite(client):
    setup_owner(client)
    tok = invite(client, "late@example.com", "viewer")
    with session_scope() as s:
        s.scalar(select(User).where(User.email == "late@example.com")).invite_expires_at = auth.now() - timedelta(minutes=1)
    assert TestClient(app).post("/api/auth/invite/accept", json={"token": tok, "name": "L", "password": PW}, headers=H).status_code == 404
    uid = next(u["id"] for u in client.get("/api/users").json() if u["email"] == "late@example.com")
    new = client.post(f"/api/users/{uid}/invite", headers=H).json()["invite_url"].split("token=")[1]
    member(new)
