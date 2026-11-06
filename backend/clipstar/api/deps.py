import hmac

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


def principal(request: Request, s: Session = Depends(get_session)) -> auth.Principal:
    """Who is calling. Raises 401 if nobody is signed in (and the install isn't in first-run setup)."""
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    p: auth.Principal | None = None
    if _token_ok(request):
        p = auth.Principal(Role.owner, via="token")
    else:
        user = auth.session_user(s, request.cookies.get(auth.COOKIE))
        if user is not None:
            p = auth.Principal(user.role, user=user)
        elif not get_settings().api_token and not auth.users_exist(s):
            p = auth.Principal(Role.owner, via="open")  # first run: open until the owner is created
    if p is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    request.state.principal = p
    return p


def authorize(request: Request, p: auth.Principal = Depends(principal)) -> auth.Principal:
    """Router dependency: role check for every route, plus a CSRF guard for browser sessions."""
    method = request.method.upper()
    if p.via == "session" and method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(auth.CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Missing request header. Reload the page and try again.")
    if not auth.allowed(p.role, method, request.url.path):
        raise HTTPException(status_code=403, detail=auth.denied_message(p.role))
    return p


# kept for compatibility with older imports
require_token = authorize


def get_workspace(s: Session = Depends(get_session)) -> Workspace:
    """Single-workspace mode for now: the first workspace, created on first use."""
    ws = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if ws is None:
        ws = Workspace(name="My workspace", settings={})
        s.add(ws)
        s.commit()
    return ws
