"""Sign-in, first-run setup, invites, team management and workspaces."""

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, mailer
from ..config import get_settings
from ..db import get_session
from ..jobs import queue
from ..models import Job, JobStatus, Membership, Role, User, UserSession, Video, Workspace
from ..storage import get_storage
from .deps import authorize, get_workspace, principal

public = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api", tags=["auth"], dependencies=[Depends(authorize)])

NOTIFY_KINDS = ["needs_approval", "post_problem", "reconnect", "video_failed", "video_ready", "report", "budget", "storage", "lead", "backup", "webhook"]


def user_out(u: User, m: Membership | None = None) -> dict:
    prefs = (m.prefs if m else u.prefs) or {}
    return {
        "id": str(u.id), "email": u.email, "name": u.name,
        "role": (m.role if m else u.role).value, "disabled": bool(m.disabled) if m else u.disabled, "is_admin": bool(u.is_admin),
        "pending_invite": u.password_hash is None, "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "prefs": {"email": bool(prefs.get("email", True)), "kinds": prefs.get("kinds", NOTIFY_KINDS)},
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def workspaces_out(s: Session, user: User | None, current: uuid.UUID | None) -> list[dict]:
    if user is None:
        rows = [(w, Role.owner) for w in s.scalars(select(Workspace).order_by(Workspace.created_at))]
    else:
        rows = list(s.execute(select(Workspace, Membership.role).join(Membership, Membership.workspace_id == Workspace.id).where(Membership.user_id == user.id, Membership.disabled.is_(False)).order_by(Membership.created_at)))
    return [{"id": str(w.id), "name": w.name, "role": r.value, "current": w.id == current} for w, r in rows]


def _set_cookie(resp: Response, raw: str) -> None:
    st = get_settings()
    resp.set_cookie(auth.COOKIE, raw, max_age=st.session_days * 86400, httponly=True, samesite="lax", secure=st.cookie_secure, path="/")


def _csrf(request: Request) -> None:
    if request.headers.get(auth.CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing request header. Reload the page and try again.")


def _first_ws(s: Session) -> Workspace:
    ws = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1).with_for_update())
    if ws is None:
        ws = Workspace(name="My workspace", settings={})
        s.add(ws)
        s.flush()
    return ws


# ---------- public ----------


@public.get("/state")
def state(request: Request, s: Session = Depends(get_session)):
    setup = not auth.users_exist(s)
    row = auth.session_row(s, request.cookies.get(auth.COOKIE))
    user = m = None
    if row:
        sess, user = row
        m = auth.membership(s, user.id, sess.workspace_id)
        if m is None:
            user = None  # signed in but no access anywhere
    ws = s.get(Workspace, m.workspace_id) if m else s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    return {
        "setup_required": setup,
        "user": user_out(user, m) if user else None,
        "workspace": {"id": str(ws.id), "name": ws.name} if ws else None,
        "workspaces": workspaces_out(s, user, ws.id if ws else None) if user else [],
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
def setup(body: SetupIn, request: Request, response: Response, s: Session = Depends(get_session)):
    _csrf(request)
    w = _first_ws(s)  # locked: serialises two setups racing
    if auth.users_exist(s):
        raise HTTPException(409, "Setup is already done. Sign in instead.")
    token = get_settings().api_token
    if token and request.headers.get("authorization") != f"Bearer {token}":
        raise HTTPException(401, "This server has an API token set. Send it to finish setup.")
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    if (p := auth.password_problem(body.password)):
        raise HTTPException(422, p)
    prefs = {"email": True, "kinds": NOTIFY_KINDS}
    u = User(workspace_id=w.id, email=email, name=body.name.strip(), role=Role.owner, is_admin=True, password_hash=auth.hash_password(body.password), prefs=prefs)
    w.name = body.workspace_name.strip()
    s.add(u)
    s.flush()
    m = Membership(user_id=u.id, workspace_id=w.id, role=Role.owner, prefs=prefs)
    s.add(m)
    s.flush()
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""), w.id)
    s.commit()
    _set_cookie(response, raw)
    return user_out(u, m)


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
                u.locked_until = auth.now() + timedelta(minutes=st.login_lock_minutes)
                u.failed_logins = 0
            s.commit()
        raise HTTPException(401, "Wrong email or password.")
    u.failed_logins = 0
    u.locked_until = None
    m = auth.membership(s, u.id)
    if m is None:
        s.commit()
        raise HTTPException(401, "Your access was removed from every workspace here. Ask an owner to add you again.")
    # come back to the workspace you used last
    last = s.scalar(select(UserSession.workspace_id).where(UserSession.user_id == u.id, UserSession.workspace_id.is_not(None)).order_by(UserSession.last_seen_at.desc()).limit(1))
    m = auth.membership(s, u.id, last)
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""), m.workspace_id)
    s.commit()
    _set_cookie(response, raw)
    return user_out(u, m)


@public.post("/logout")
def logout(request: Request, response: Response, s: Session = Depends(get_session)):
    raw = request.cookies.get(auth.COOKIE)
    if raw:
        for sess in s.scalars(select(UserSession).where(UserSession.token_hash == auth.token_hash(raw))):
            s.delete(sess)
        s.commit()
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


def _invite_membership(s: Session, u: User) -> Membership | None:
    return s.scalar(select(Membership).where(Membership.user_id == u.id, Membership.disabled.is_(False)).order_by(Membership.created_at.desc()).limit(1))


@public.get("/invite/{token}")
def invite_info(token: str, s: Session = Depends(get_session)):
    u = auth.find_invite(s, token)
    m = _invite_membership(s, u) if u else None
    if u is None or m is None:
        raise HTTPException(404, "This invite link has expired or was already used. Ask an owner for a new one.")
    ws = s.get(Workspace, m.workspace_id)
    return {"email": u.email, "name": u.name, "role": m.role.value, "workspace": ws.name if ws else ""}


class AcceptIn(BaseModel):
    token: str
    name: str = Field(min_length=1, max_length=200)
    password: str


@public.post("/invite/accept")
def accept(body: AcceptIn, request: Request, response: Response, s: Session = Depends(get_session)):
    _csrf(request)
    u = auth.find_invite(s, body.token)
    m = _invite_membership(s, u) if u else None
    if u is None or m is None:
        raise HTTPException(404, "This invite link has expired or was already used. Ask an owner for a new one.")
    if (p := auth.password_problem(body.password)):
        raise HTTPException(422, p)
    u.password_hash = auth.hash_password(body.password)
    u.name = body.name.strip()
    u.invite_hash = None
    u.invite_expires_at = None
    auth.end_sessions(s, u.id)
    raw = auth.new_session(s, u, request.headers.get("user-agent", ""), m.workspace_id)
    s.commit()
    _set_cookie(response, raw)
    return user_out(u, m)


# ---------- signed in ----------


@router.get("/auth/me")
def me(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    return {"user": user_out(p.user, p.membership) if p.user else None, "role": p.role.value, "via": p.via, "workspace_id": str(p.workspace_id) if p.workspace_id else None, "workspaces": workspaces_out(s, p.user, p.workspace_id)}


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
    m = s.get(Membership, p.membership.id, with_for_update=True) if p.membership is not None else None
    if m is not None and (body.email_notifications is not None or body.kinds is not None):
        prefs = dict(m.prefs or {})  # per workspace: you may want emails from one creator's workspace and not another
        if body.email_notifications is not None:
            prefs["email"] = body.email_notifications
        if body.kinds is not None:
            prefs["kinds"] = [k for k in body.kinds if k in NOTIFY_KINDS]
        m.prefs = prefs
    s.commit()
    return user_out(u, m)


# ---------- team (in the current workspace) ----------


@router.get("/users")
def list_users(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    rows = s.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(Membership.workspace_id == ws.id).order_by(Membership.created_at))
    return [user_out(u, m) for u, m in rows]


class InviteIn(BaseModel):
    email: str
    name: str = Field(default="", max_length=200)
    role: Literal["owner", "editor", "reviewer", "viewer"] = "editor"


def _send(u: User, subject: str, body: str) -> bool:
    if not mailer.configured():
        return False
    try:
        mailer.send([u.email], subject, body)
        return True
    except Exception:
        return False


def _invite_mail(u: User, raw: str, ws: Workspace, role: Role) -> bool:
    return _send(u, f"You're invited to {ws.name} on clip_star", f"Hi{(' ' + u.name) if u.name else ''},\n\nYou've been invited to {ws.name} on clip_star as {role.value}.\nSet your password here (the link works for 7 days):\n\n{auth.invite_url(raw)}\n")


@router.post("/users", status_code=201)
def invite(body: InviteIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    role = Role(body.role)
    u = s.scalar(select(User).where(User.email == email))
    if u is not None:
        m = s.scalar(select(Membership).where(Membership.user_id == u.id, Membership.workspace_id == ws.id))
        if m is not None and not m.disabled:
            raise HTTPException(409, "Someone with this email is already on the team.")
        if m is None:
            m = Membership(user_id=u.id, workspace_id=ws.id, role=role, prefs={"email": True, "kinds": NOTIFY_KINDS})
            s.add(m)
        else:
            m.disabled, m.role = False, role
        out = {"invite_url": None, "emailed": False}
        if u.password_hash is None:  # never finished an earlier invite: send a fresh link
            raw = auth.new_invite(u)
            out = {"invite_url": auth.invite_url(raw)}
            s.commit()
            out["emailed"] = _invite_mail(u, raw, ws, role)
        else:
            s.commit()
            out["emailed"] = _send(u, f"You were added to {ws.name} on clip_star", f"You now have {role.value} access to {ws.name}. Switch to it from the workspace menu in clip_star.\n\n{get_settings().web_url}\n")
        return {**user_out(u, m), **out, "added_existing": u.password_hash is not None}
    u = User(workspace_id=ws.id, email=email, name=body.name.strip(), role=role, prefs={"email": True, "kinds": NOTIFY_KINDS})
    raw = auth.new_invite(u)
    s.add(u)
    s.flush()
    m = Membership(user_id=u.id, workspace_id=ws.id, role=role, prefs={"email": True, "kinds": NOTIFY_KINDS})
    s.add(m)
    s.commit()
    return {**user_out(u, m), "invite_url": auth.invite_url(raw), "emailed": _invite_mail(u, raw, ws, role), "added_existing": False}


def _team_member(s: Session, ws: Workspace, user_id: uuid.UUID) -> tuple[User, Membership]:
    m = s.scalar(select(Membership).where(Membership.user_id == user_id, Membership.workspace_id == ws.id).with_for_update())
    u = s.get(User, user_id) if m else None
    if m is None or u is None:
        raise HTTPException(404, "Person not found.")
    return u, m


def _other_owners(s: Session, ws: Workspace, user_id: uuid.UUID) -> int:
    return s.scalar(
        select(func.count(Membership.id)).join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == ws.id, Membership.role == Role.owner, Membership.disabled.is_(False), Membership.user_id != user_id, User.password_hash.is_not(None))
    ) or 0


@router.post("/users/{user_id}/invite")
def reinvite(user_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u, m = _team_member(s, ws, user_id)
    if u.password_hash:
        raise HTTPException(409, "This person already set a password.")
    raw = auth.new_invite(u)
    s.commit()
    return {**user_out(u, m), "invite_url": auth.invite_url(raw), "emailed": _invite_mail(u, raw, ws, m.role)}


class UserPatch(BaseModel):
    role: Literal["owner", "editor", "reviewer", "viewer"] | None = None
    disabled: bool | None = None
    name: str | None = Field(default=None, max_length=200)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u, m = _team_member(s, ws, user_id)
    losing_owner = m.role == Role.owner and ((body.role and body.role != "owner") or body.disabled)
    if losing_owner and _other_owners(s, ws, u.id) == 0:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    if body.role:
        m.role = Role(body.role)
    if body.name is not None:
        u.name = body.name.strip()
    if body.disabled is not None:
        m.disabled = body.disabled  # access to this workspace only; their other workspaces are unaffected
    s.commit()
    return user_out(u, m)


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    u, m = _team_member(s, ws, user_id)
    if m.role == Role.owner and _other_owners(s, ws, u.id) == 0:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    s.delete(m)
    s.flush()
    if not u.is_admin and not s.scalar(select(Membership.id).where(Membership.user_id == u.id).limit(1)):
        s.delete(u)  # in no workspace any more
    s.commit()


# ---------- workspaces ----------


@router.get("/workspaces")
def list_workspaces(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    return workspaces_out(s, p.user, p.workspace_id)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    """A separate space (e.g. one per creator or brand): its own videos, accounts, team, platform apps and settings."""
    if p.user is None:
        raise HTTPException(409, "Sign in as a person to create a workspace.")
    owner_somewhere = s.scalar(select(Membership.id).where(Membership.user_id == p.user.id, Membership.role == Role.owner, Membership.disabled.is_(False)).limit(1))
    if not (p.user.is_admin or owner_somewhere):
        raise HTTPException(403, "Only owners can create workspaces.")
    w = Workspace(name=body.name.strip(), settings={})
    s.add(w)
    s.flush()
    s.add(Membership(user_id=p.user.id, workspace_id=w.id, role=Role.owner, prefs={"email": True, "kinds": NOTIFY_KINDS}))
    if p.session is not None:
        s.get(UserSession, p.session.id).workspace_id = w.id  # switch to it
    s.commit()
    return {"id": str(w.id), "name": w.name, "role": "owner", "current": True}


@router.post("/workspaces/{workspace_id}/switch")
def switch_workspace(workspace_id: uuid.UUID, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    if p.via != "session" or p.user is None:
        raise HTTPException(409, "Only a signed-in person switches workspaces. Scripts pick one with their API key or the X-ClipStar-Workspace header.")
    m = auth.membership(s, p.user.id, workspace_id)
    if m is None or m.workspace_id != workspace_id:
        raise HTTPException(404, "You're not in that workspace.")
    s.get(UserSession, p.session.id).workspace_id = workspace_id
    s.commit()
    w = s.get(Workspace, workspace_id)
    return {"id": str(w.id), "name": w.name, "role": m.role.value, "current": True}


class DeleteWorkspaceIn(BaseModel):
    confirm_name: str


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: uuid.UUID, body: DeleteWorkspaceIn, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    """Deletes everything in the workspace: videos and clips (files too), accounts, posts, stats, settings. Can't be undone."""
    w = s.get(Workspace, workspace_id, with_for_update=True)
    if w is None:
        raise HTTPException(404, "Workspace not found.")
    if p.user is not None:
        m = auth.membership(s, p.user.id, workspace_id)
        if m is None or m.workspace_id != workspace_id or m.role != Role.owner:
            raise HTTPException(403, "Only an owner of this workspace can delete it.")
    if body.confirm_name.strip() != w.name:
        raise HTTPException(422, "Type the workspace's name exactly to confirm.")
    if (s.scalar(select(func.count(Workspace.id))) or 0) <= 1:
        raise HTTPException(409, "This is the only workspace on this server; it can't be deleted.")
    video_ids = list(s.scalars(select(Video.id).where(Video.workspace_id == w.id)))
    if video_ids:
        for j in s.scalars(select(Job).where(Job.video_id.in_(video_ids), Job.status.in_([JobStatus.queued, JobStatus.running])).with_for_update()):
            queue.cancel(s, j)
    s.delete(w)
    s.commit()
    for vid in video_ids:
        get_storage().delete_video(vid)
