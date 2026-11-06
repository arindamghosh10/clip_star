"""Sign-in, first-run setup, invites and team management."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, mailer
from ..config import get_settings
from ..db import get_session
from ..models import Role, User, Workspace
from .deps import authorize, get_workspace, principal

public = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api", tags=["auth"], dependencies=[Depends(authorize)])

NOTIFY_KINDS = ["needs_approval", "post_problem", "reconnect", "video_failed", "video_ready", "report", "budget", "storage", "lead", "backup"]


def user_out(u: User) -> dict:
    return {
        "id": str(u.id), "email": u.email, "name": u.name, "role": u.role.value, "disabled": u.disabled,
        "pending_invite": u.password_hash is None, "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "prefs": {"email": bool((u.prefs or {}).get("email", True)), "kinds": (u.prefs or {}).get("kinds", NOTIFY_KINDS)},
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _set_cookie(resp: Response, raw: str) -> None:
    st = get_settings()
    resp.set_cookie(auth.COOKIE, raw, max_age=st.session_days * 86400, httponly=True, samesite="lax", secure=st.cookie_secure, path="/")


def _csrf(request: Request) -> None:
    if request.headers.get(auth.CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing request header. Reload the page and try again.")


# ---------- public ----------


@public.get("/state")
def state(request: Request, s: Session = Depends(get_session)):
    setup = not auth.users_exist(s)
    user = auth.session_user(s, request.cookies.get(auth.COOKIE))
    ws = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    return {
        "setup_required": setup,
        "user": user_out(user) if user else None,
        "token_required": bool(get_settings().api_token) and setup,
        "setup_done": bool(ws and (ws.settings or {}).get("setup_done")),
        "email_enabled": mailer.configured(),
        "roles": {r.value: h for r, h in auth.ROLE_HELP.items()},
    }


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str
    password: str
    workspace_name: str = Field(min_length=1, max_length=200)


@public.post("/setup", status_code=201)
def setup(body: SetupIn, request: Request, response: Response, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    _csrf(request)
    w = s.get(Workspace, ws.id, with_for_update=True)  # serialises two setups racing
    if auth.users_exist(s):
        raise HTTPException(409, "Setup is already done. Sign in instead.")
    if get_settings().api_token:
        token = get_settings().api_token
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(401, "This server has an API token set. Send it to finish setup.")
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    if (p := auth.password_problem(body.password)) :
        raise HTTPException(422, p)
    u = User(workspace_id=w.id, email=email, name=body.name.strip(), role=Role.owner, password_hash=auth.hash_password(body.password), prefs={"email": True, "kinds": NOTIFY_KINDS})
    w.name = body.workspace_name.strip()
    s.add(u)
    s.flush()
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""))
    s.commit()
    _set_cookie(response, raw)
    return user_out(u)


class LoginIn(BaseModel):
    email: str
    password: str


@public.post("/login")
def login(body: LoginIn, request: Request, response: Response, s: Session = Depends(get_session)):
    _csrf(request)
    st = get_settings()
    u = s.scalar(select(User).where(User.email == auth.normalize_email(body.email)).with_for_update())
    if u is not None and u.locked_until and u.locked_until > auth.now():
        mins = max(1, int((u.locked_until - auth.now()).total_seconds() // 60) + 1)
        raise HTTPException(429, f"Too many wrong passwords. Try again in {mins} minute{'s' if mins != 1 else ''}.")
    ok = auth.verify_password(body.password, u.password_hash if u else None)
    if not ok or u is None or u.disabled:
        if u is not None and not u.disabled:
            u.failed_logins += 1
            if u.failed_logins >= st.login_max_failures:
                from datetime import timedelta

                u.locked_until = auth.now() + timedelta(minutes=st.login_lock_minutes)
                u.failed_logins = 0
            s.commit()
        raise HTTPException(401, "Wrong email or password.")
    u.failed_logins = 0
    u.locked_until = None
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""))
    s.commit()
    _set_cookie(response, raw)
    return user_out(u)


@public.post("/logout")
def logout(request: Request, response: Response, s: Session = Depends(get_session)):
    raw = request.cookies.get(auth.COOKIE)
    if raw:
        from ..models import UserSession

        for sess in s.scalars(select(UserSession).where(UserSession.token_hash == auth.token_hash(raw))):
            s.delete(sess)
        s.commit()
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@public.get("/invite/{token}")
def invite_info(token: str, s: Session = Depends(get_session)):
    u = auth.find_invite(s, token)
    if u is None:
        raise HTTPException(404, "This invite link has expired or was already used. Ask an owner for a new one.")
    ws = s.get(Workspace, u.workspace_id)
    return {"email": u.email, "name": u.name, "role": u.role.value, "workspace": ws.name if ws else ""}


class AcceptIn(BaseModel):
    token: str
    name: str = Field(min_length=1, max_length=200)
    password: str


@public.post("/invite/accept")
def accept(body: AcceptIn, request: Request, response: Response, s: Session = Depends(get_session)):
    _csrf(request)
    u = auth.find_invite(s, body.token)
    if u is None:
        raise HTTPException(404, "This invite link has expired or was already used. Ask an owner for a new one.")
    if (p := auth.password_problem(body.password)):
        raise HTTPException(422, p)
    u.password_hash = auth.hash_password(body.password)
    u.name = body.name.strip()
    u.invite_hash = None
    u.invite_expires_at = None
    auth.end_sessions(s, u.id)
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""))
    s.commit()
    _set_cookie(response, raw)
    return user_out(u)


# ---------- signed in ----------


@router.get("/auth/me")
def me(p: auth.Principal = Depends(principal)):
    return {"user": user_out(p.user) if p.user else None, "role": p.role.value, "via": p.via}


class MeIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    current_password: str | None = None
    new_password: str | None = None
    email_notifications: bool | None = None
    kinds: list[str] | None = None


@router.patch("/auth/me")
def update_me(body: MeIn, request: Request, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    if p.user is None:
        raise HTTPException(409, "You're not signed in as a person (API token or first-run setup).")
    u = s.get(User, p.user.id, with_for_update=True)
    if body.name is not None:
        u.name = body.name.strip()
    if body.new_password is not None:
        if not auth.verify_password(body.current_password or "", u.password_hash):
            raise HTTPException(403, "Your current password is wrong.")
        if (problem := auth.password_problem(body.new_password)):
            raise HTTPException(422, problem)
        u.password_hash = auth.hash_password(body.new_password)
        auth.end_sessions(s, u.id, keep_hash=auth.token_hash(request.cookies.get(auth.COOKIE, "")))  # sign out other devices
    prefs = dict(u.prefs or {})
    if body.email_notifications is not None:
        prefs["email"] = body.email_notifications
    if body.kinds is not None:
        prefs["kinds"] = [k for k in body.kinds if k in NOTIFY_KINDS]
    u.prefs = prefs
    s.commit()
    return user_out(u)


@router.get("/users")
def list_users(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return [user_out(u) for u in s.scalars(select(User).where(User.workspace_id == ws.id).order_by(User.created_at))]


class InviteIn(BaseModel):
    email: str
    name: str = Field(default="", max_length=200)
    role: Literal["owner", "editor", "reviewer", "viewer"] = "editor"


def _send_invite(u: User, raw: str, ws: Workspace) -> bool:
    if not mailer.configured():
        return False
    try:
        mailer.send([u.email], f"You're invited to {ws.name} on clip_star", f"Hi{(' ' + u.name) if u.name else ''},\n\nYou've been invited to {ws.name} on clip_star as {u.role.value}.\nSet your password here (the link works for 7 days):\n\n{auth.invite_url(raw)}\n")
        return True
    except Exception:
        return False


@router.post("/users", status_code=201)
def invite(body: InviteIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    if s.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Someone with this email is already on the team.")
    u = User(workspace_id=ws.id, email=email, name=body.name.strip(), role=Role(body.role), prefs={"email": True, "kinds": NOTIFY_KINDS})
    raw = auth.new_invite(u)
    s.add(u)
    s.commit()
    sent = _send_invite(u, raw, ws)
    return {**user_out(u), "invite_url": auth.invite_url(raw), "emailed": sent}


def _team_user(s: Session, ws: Workspace, user_id: uuid.UUID) -> User:
    u = s.get(User, user_id, with_for_update=True)
    if u is None or u.workspace_id != ws.id:
        raise HTTPException(404, "Person not found.")
    return u


def _other_owners(s: Session, ws: Workspace, u: User) -> int:
    return s.scalar(select(func.count(User.id)).where(User.workspace_id == ws.id, User.role == Role.owner, User.disabled.is_(False), User.id != u.id, User.password_hash.is_not(None))) or 0


@router.post("/users/{user_id}/invite")
def reinvite(user_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u = _team_user(s, ws, user_id)
    if u.password_hash:
        raise HTTPException(409, "This person already set a password.")
    raw = auth.new_invite(u)
    s.commit()
    return {**user_out(u), "invite_url": auth.invite_url(raw), "emailed": _send_invite(u, raw, ws)}


class UserPatch(BaseModel):
    role: Literal["owner", "editor", "reviewer", "viewer"] | None = None
    disabled: bool | None = None
    name: str | None = Field(default=None, max_length=200)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u = _team_user(s, ws, user_id)
    losing_owner = u.role == Role.owner and ((body.role and body.role != "owner") or body.disabled)
    if losing_owner and _other_owners(s, ws, u) == 0:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    if body.role:
        u.role = Role(body.role)
    if body.name is not None:
        u.name = body.name.strip()
    if body.disabled is not None:
        u.disabled = body.disabled
        if body.disabled:
            auth.end_sessions(s, u.id)
    s.commit()
    return user_out(u)


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u = _team_user(s, ws, user_id)
    if u.role == Role.owner and _other_owners(s, ws, u) == 0:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    s.delete(u)
    s.commit()
