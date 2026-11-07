import hmac
import re
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..config import get_settings
from ..db import get_session
from ..models import Role, Workspace


def _token_ok(request: Request) -> bool:
    token = get_settings().api_token
    header = request.headers.get("authorization")
    return bool(token and header and hmac.compare_digest(header, f"Bearer {token}"))


def _first_workspace(s: Session) -> Workspace:
    ws = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if ws is None:
        ws = Workspace(name="My workspace", settings={})
        s.add(ws)
        s.commit()
    return ws


def principal(request: Request, s: Session = Depends(get_session)) -> auth.Principal:
    """Who is calling, and in which workspace. Raises 401 if nobody is signed in (and this isn't first-run setup)."""
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    p: auth.Principal | None = None
    header = request.headers.get("authorization") or ""
    if header.startswith("Bearer " + auth.KEY_PREFIX):
        p = auth.key_principal(s, header[7:].strip())
        if p is None:
            raise HTTPException(status_code=401, detail="This API key is wrong or was revoked.")
        if not auth.rate_ok(p.key_id or "", get_settings().api_key_rate_per_minute):
            raise HTTPException(status_code=429, detail="Too many requests with this API key. Slow down and retry in a minute.", headers={"Retry-After": "60"})
    elif _token_ok(request):
        ws = None
        wanted = request.headers.get("x-clipstar-workspace")
        if wanted:
            try:
                ws = s.get(Workspace, uuid.UUID(wanted))
            except ValueError:
                ws = None
            if ws is None:
                raise HTTPException(status_code=404, detail="No such workspace.")
        p = auth.Principal(Role.owner, via="token", workspace_id=(ws or _first_workspace(s)).id)
    else:
        row = auth.session_row(s, request.cookies.get(auth.COOKIE))
        if row is not None:
            sess, user = row
            m = auth.membership(s, user.id, sess.workspace_id)
            if m is None:
                raise HTTPException(status_code=401, detail="You no longer have access to any workspace here. Ask an owner to add you.")
            if sess.workspace_id != m.workspace_id:
                sess.workspace_id = m.workspace_id
                s.commit()
            p = auth.Principal(m.role, user=user, workspace_id=m.workspace_id, membership=m, session=sess)
        elif not get_settings().api_token and not auth.users_exist(s):
            p = auth.Principal(Role.owner, via="open", workspace_id=_first_workspace(s).id)  # first run: open until the owner is created
    if p is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    request.state.principal = p
    return p


def authorize(request: Request, p: auth.Principal = Depends(principal)) -> auth.Principal:
    """Router dependency: role check for every route, plus a CSRF guard for browser sessions."""
    method = request.method.upper()
    path = request.url.path
    if p.via == "key" and path.startswith(("/api/keys", "/api/auth/", "/api/workspaces")) and method not in ("GET", "HEAD"):
        raise HTTPException(status_code=403, detail="API keys can't manage keys, sign-in or workspaces. Use the app.")
    if any(re.search(x, path) for x in auth.ADMIN_ONLY):
        if not p.admin:
            raise HTTPException(status_code=403, detail="Only the person who runs this server can do this (backups and server clean-up cover every workspace).")
        if p.via == "session" and method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(auth.CSRF_HEADER) != "1":
            raise HTTPException(status_code=403, detail="Missing request header. Reload the page and try again.")
        return p
    if p.via == "session" and method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(auth.CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Missing request header. Reload the page and try again.")
    if not auth.allowed(p.role, method, request.url.path):
        raise HTTPException(status_code=403, detail=auth.denied_message(p.role))
    return p


# kept for compatibility with older imports
require_token = authorize


def get_workspace(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)) -> Workspace:
    """The workspace this request works in (from the sign-in, the API key, or the X-ClipStar-Workspace header with the server token)."""
    ws = s.get(Workspace, p.workspace_id) if p.workspace_id else None
    if ws is None:
        raise HTTPException(status_code=404, detail="That workspace no longer exists. Reload the page.")
    return ws
