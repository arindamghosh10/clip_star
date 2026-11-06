import hmac

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import Workspace


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if not token:
        return
    expected = f"Bearer {token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Missing or wrong API token.")


def get_workspace(s: Session = Depends(get_session)) -> Workspace:
    """Single-workspace mode for now: the first workspace, created on first use."""
    ws = s.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if ws is None:
        ws = Workspace(name="My workspace", settings={})
        s.add(ws)
        s.commit()
    return ws
