"""Platform apps (your developer app keys) and connecting accounts through each platform's login."""

import secrets as pysecrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..errors import ClipstarError
from ..models import Account, AccountStatus, OAuthState, Platform, PlatformApp, Workspace
from ..platforms.base import pkce_pair
from ..platforms.registry import PROVIDERS
from ..publishing.service import get_app, save_tokens
from ..secrets import decrypt_json, encrypt
from ..storage import get_storage
from .deps import get_workspace, require_token

router = APIRouter(prefix="/api", tags=["connect"], dependencies=[Depends(require_token)])
public = APIRouter(prefix="/api", tags=["public"])  # browser redirects and platform fetches: no API token

STATE_TTL = timedelta(minutes=15)


def redirect_uri(platform: str) -> str:
    return f"{get_settings().public_api_url.rstrip('/')}/api/connect/{platform}/callback"


class AppIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=500)


@router.get("/platforms")
def list_platforms(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    apps = {a.platform.value: a for a in s.scalars(select(PlatformApp).where(PlatformApp.workspace_id == ws.id))}
    out = []
    for key, p in PROVIDERS.items():
        a = apps.get(key)
        out.append(
            {
                "platform": key,
                "label": p.label,
                "configured": a is not None,
                "client_id": a.client_id if a else None,  # the id isn't secret; the secret is never returned
                "client_id_label": p.client_id_label,
                "redirect_uri": redirect_uri(key),
                "scopes": p.scopes,
                "docs_url": p.docs_url,
            }
        )
    return out


@router.put("/platforms/{platform}/app")
def save_app(platform: Platform, body: AppIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    row = s.get(PlatformApp, (ws.id, platform))
    if row is None:
        row = PlatformApp(workspace_id=ws.id, platform=platform, client_id=body.client_id.strip(), secret_enc=encrypt(body.client_secret.strip()))
        s.add(row)
    else:
        row.client_id = body.client_id.strip()
        row.secret_enc = encrypt(body.client_secret.strip())
    s.commit()
    return {"ok": True}


@router.delete("/platforms/{platform}/app", status_code=204)
def delete_app(platform: Platform, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    s.execute(delete(PlatformApp).where(PlatformApp.workspace_id == ws.id, PlatformApp.platform == platform))
    s.commit()


class StartIn(BaseModel):
    group_name: str = Field(default="", max_length=100)


@router.post("/connect/{platform}/start")
def start_connect(platform: Platform, body: StartIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    app = get_app(s, ws.id, platform.value)
    if app is None:
        raise HTTPException(409, f"Add your {PROVIDERS[platform.value].label} app keys first (Settings → Platform apps).")
    s.execute(delete(OAuthState).where(OAuthState.created_at < datetime.now(timezone.utc) - STATE_TTL))
    state = pysecrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    s.add(OAuthState(state=state, workspace_id=ws.id, platform=platform, verifier=verifier, group_name=body.group_name.strip()))
    s.commit()
    return {"authorize_url": PROVIDERS[platform.value].auth_url(app, state, redirect_uri(platform.value), challenge)}


def _back(**params) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().web_url.rstrip('/')}/accounts?{urlencode(params)}", status_code=302)


@public.get("/connect/{platform}/callback")
def connect_callback(platform: Platform, state: str = "", code: str = "", error: str = "", error_description: str = "", s: Session = Depends(get_session)):
    row = s.get(OAuthState, state) if state else None
    if row is None or row.platform != platform or row.created_at < datetime.now(timezone.utc) - STATE_TTL:
        return _back(error="This connect link expired or wasn't started here. Please try again.")
    ws_id, verifier, group = row.workspace_id, row.verifier, row.group_name
    s.delete(row)  # one use only
    s.commit()
    if error or not code:
        return _back(error=f"{PROVIDERS[platform.value].label} said: {error_description or error or 'no permission was given'}")
    prov = PROVIDERS[platform.value]
    app = get_app(s, ws_id, platform.value)
    if app is None:
        return _back(error="The app keys were removed while connecting.")
    try:
        tokens = prov.exchange(app, code, redirect_uri(platform.value), verifier)
        idents = prov.identities(app, tokens)
    except ClipstarError as e:
        return _back(error=e.user_message)
    names = []
    for idn in idents:
        acc = s.scalar(select(Account).where(Account.workspace_id == ws_id, Account.platform == platform, Account.remote_id == idn.remote_id))
        if acc is None:
            acc = s.scalar(select(Account).where(Account.workspace_id == ws_id, Account.platform == platform, Account.handle == idn.handle))
        if acc is None:
            acc = Account(workspace_id=ws_id, platform=platform, handle=idn.handle, group_name=group)
            s.add(acc)
        acc.handle = idn.handle
        acc.remote_id = idn.remote_id
        acc.connection = "oauth"
        acc.status = AccountStatus.connected
        acc.last_error = None
        acc.options = {**(acc.options or {}), **idn.options}
        save_tokens(acc, idn.tokens)
        names.append(idn.handle)
    s.commit()
    return _back(connected=", ".join(names), platform=platform.value)


@public.get("/public/media/{token}")
def public_media(token: str):
    """Short-lived link a platform uses to download a clip (Threads). The token is encrypted and expires."""
    try:
        d = decrypt_json(token)
    except ClipstarError:
        raise HTTPException(404, "Not found.") from None
    if not isinstance(d, dict) or d.get("exp", 0) < time.time():
        raise HTTPException(404, "Not found.")
    st = get_storage()
    if not st.exists(d["p"]):
        raise HTTPException(404, "Not found.")
    return FileResponse(st.abs(d["p"]), media_type="video/mp4")
