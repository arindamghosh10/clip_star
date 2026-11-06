"""Personal API keys, the event feed and webhooks."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, webhooks
from ..db import get_session
from ..events import EVENT_TYPES
from ..models import ApiKey, Event, Role, User, Webhook, WebhookDelivery, Workspace
from .deps import authorize, get_workspace, principal

router = APIRouter(prefix="/api", tags=["integrations"], dependencies=[Depends(authorize)])


# ---------- API keys ----------


def _key_out(k: ApiKey, owner: User | None = None) -> dict:
    return {
        "id": str(k.id), "name": k.name, "prefix": k.prefix, "role": k.role.value, "user_id": str(k.user_id), "user_email": owner.email if owner else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None, "revoked": k.revoked_at is not None, "created_at": k.created_at.isoformat() if k.created_at else None,
    }


@router.get("/keys")
def list_keys(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace), p: auth.Principal = Depends(principal)):
    q = select(ApiKey, User).join(User, User.id == ApiKey.user_id).where(ApiKey.workspace_id == ws.id, ApiKey.revoked_at.is_(None)).order_by(ApiKey.created_at.desc())
    if p.role != Role.owner:
        q = q.where(ApiKey.user_id == p.user_id)
    return [_key_out(k, u) for k, u in s.execute(q)]


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: Role = Role.viewer


@router.post("/keys", status_code=201)
def create_key(body: KeyIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace), p: auth.Principal = Depends(principal)):
    if p.user is None:
        raise HTTPException(409, "Sign in as a person to create API keys (they act as you).")
    if auth.RANK[body.role] > auth.RANK[p.role]:
        raise HTTPException(403, f"A key can't have more access than you ({p.role.value}).")
    raw, prefix, h = auth.new_api_key()
    k = ApiKey(workspace_id=ws.id, user_id=p.user.id, name=body.name.strip(), prefix=prefix, key_hash=h, role=body.role)
    s.add(k)
    s.commit()
    return {**_key_out(k, p.user), "key": raw}


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace), p: auth.Principal = Depends(principal)):
    k = s.get(ApiKey, key_id, with_for_update=True)
    if k is None or k.workspace_id != ws.id or (p.role != Role.owner and k.user_id != p.user_id):
        raise HTTPException(404, "Key not found.")
    k.revoked_at = auth.now()
    s.commit()


# ---------- event feed ----------


@router.get("/events")
def events(
    after: int = Query(0, ge=0, description="Return events with an id greater than this (the last id you saw)"),
    types: str | None = Query(None, description="Comma-separated event types, e.g. post.published,video.ready"),
    limit: int = Query(50, ge=1, le=500),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    q = select(Event).where(Event.workspace_id == ws.id, Event.id > after, Event.type != "ping")
    if types:
        q = q.where(Event.type.in_([t.strip() for t in types.split(",") if t.strip()]))
    items = list(s.scalars(q.order_by(Event.id).limit(limit)))
    return {"events": [webhooks.payload(e) for e in items], "next_after": items[-1].id if items else after, "types": EVENT_TYPES}


@router.get("/events/types")
def event_types():
    return EVENT_TYPES


# ---------- webhooks ----------


def _wh_out(h: Webhook) -> dict:
    return {
        "id": str(h.id), "url": h.url, "description": h.description, "events": h.events, "enabled": h.enabled,
        "consecutive_failures": h.consecutive_failures, "disabled_reason": h.disabled_reason,
        "last_delivery_at": h.last_delivery_at.isoformat() if h.last_delivery_at else None, "created_at": h.created_at.isoformat() if h.created_at else None,
    }


def _check_events(evs: list[str]) -> list[str]:
    evs = sorted(set(evs))
    bad = [e for e in evs if e != "*" and e not in EVENT_TYPES]
    if bad:
        raise HTTPException(422, f"Unknown event: {', '.join(bad)}.")
    if not evs:
        raise HTTPException(422, "Pick at least one event (or * for all).")
    return evs


class WebhookIn(BaseModel):
    url: str
    events: list[str] = ["*"]
    description: str = Field(default="", max_length=200)


@router.get("/webhooks")
def list_webhooks(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return [_wh_out(h) for h in s.scalars(select(Webhook).where(Webhook.workspace_id == ws.id).order_by(Webhook.created_at))]


@router.post("/webhooks", status_code=201)
def create_webhook(body: WebhookIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    try:
        url = webhooks.check_url(body.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    secret = webhooks.new_secret()
    h = Webhook(workspace_id=ws.id, url=url, description=body.description.strip(), events=_check_events(body.events), secret_enc=webhooks.store_secret(secret))
    s.add(h)
    s.commit()
    return {**_wh_out(h), "secret": secret}


class WebhookPatch(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


def _hook(s: Session, ws: Workspace, hook_id: uuid.UUID) -> Webhook:
    h = s.get(Webhook, hook_id, with_for_update=True)
    if h is None or h.workspace_id != ws.id:
        raise HTTPException(404, "Webhook not found.")
    return h


@router.patch("/webhooks/{hook_id}")
def update_webhook(hook_id: uuid.UUID, body: WebhookPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    h = _hook(s, ws, hook_id)
    if body.url is not None:
        try:
            h.url = webhooks.check_url(body.url)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    if body.events is not None:
        h.events = _check_events(body.events)
    if body.description is not None:
        h.description = body.description.strip()
    if body.enabled is not None:
        h.enabled = body.enabled
        if body.enabled:
            h.consecutive_failures, h.disabled_reason = 0, None
    s.commit()
    return _wh_out(h)


@router.post("/webhooks/{hook_id}/secret")
def rotate_secret(hook_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    h = _hook(s, ws, hook_id)
    secret = webhooks.new_secret()
    h.secret_enc = webhooks.store_secret(secret)
    s.commit()
    return {**_wh_out(h), "secret": secret}


@router.delete("/webhooks/{hook_id}", status_code=204)
def delete_webhook(hook_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    s.delete(_hook(s, ws, hook_id))
    s.commit()


@router.post("/webhooks/{hook_id}/test", status_code=202)
def test_webhook(hook_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    h = _hook(s, ws, hook_id)
    ev = Event(workspace_id=ws.id, type="ping", data={"message": "Test delivery from clip_star."}, fanned_out=True)
    s.add(ev)
    s.flush()
    d = webhooks.queue_delivery(s, h, ev)
    s.commit()
    return {"delivery_id": str(d.id)}


def _d_out(d: WebhookDelivery) -> dict:
    return {
        "id": str(d.id), "event_id": d.event_id, "event_type": d.event_type, "status": d.status, "attempts": d.attempts,
        "response_code": d.response_code, "error": d.error, "created_at": d.created_at.isoformat() if d.created_at else None,
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
    }


@router.get("/webhooks/{hook_id}/deliveries")
def deliveries(hook_id: uuid.UUID, limit: int = Query(30, ge=1, le=200), s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    h = _hook(s, ws, hook_id)
    return [_d_out(d) for d in s.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_id == h.id).order_by(WebhookDelivery.created_at.desc()).limit(limit))]


@router.post("/webhooks/{hook_id}/deliveries/{delivery_id}/retry", status_code=202)
def redeliver(hook_id: uuid.UUID, delivery_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    h = _hook(s, ws, hook_id)
    old = s.get(WebhookDelivery, delivery_id)
    if old is None or old.webhook_id != h.id:
        raise HTTPException(404, "Delivery not found.")
    ev = s.get(Event, old.event_id)
    d = webhooks.queue_delivery(s, h, ev)
    s.commit()
    return {"delivery_id": str(d.id)}
