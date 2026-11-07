"""Notifications, spending limits, storage and backups."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, backup, budget, maintenance
from ..config import get_settings
from ..jobs import queue
from ..db import get_session
from ..models import Notification, User, Workspace
from .deps import authorize, get_workspace, principal

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(authorize)])


# ---------- notifications ----------


def _n_out(n: Notification, seen_at) -> dict:
    return {
        "id": str(n.id), "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
        "created_at": n.created_at.isoformat(), "unread": seen_at is None or n.created_at > seen_at,
    }


@router.get("/notifications")
def notifications(limit: int = 30, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace), p: auth.Principal = Depends(principal)):
    seen = p.membership.notifications_seen_at if p.membership is not None else None
    items = list(s.scalars(select(Notification).where(Notification.workspace_id == ws.id).order_by(Notification.created_at.desc()).limit(max(1, min(limit, 100)))))
    unread = s.scalar(select(func.count(Notification.id)).where(Notification.workspace_id == ws.id, *( [Notification.created_at > seen] if seen else [] ))) or 0
    return {"unread": unread, "items": [_n_out(n, seen) for n in items]}


@router.post("/notifications/seen")
def mark_seen(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    if p.membership is None:
        return {"ok": True}
    from ..models import Membership

    m = s.get(Membership, p.membership.id, with_for_update=True)
    m.notifications_seen_at = func.now()
    s.commit()
    return {"ok": True}


# ---------- budget ----------


@router.get("/admin/budget")
def get_budget(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return budget.summary(s, ws)


class BudgetIn(BaseModel):
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    budget_warn_pct: int = Field(default=80, ge=10, le=99)


@router.put("/admin/budget")
def set_budget(body: BudgetIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    w = s.get(Workspace, ws.id, with_for_update=True)
    w.settings = {**(w.settings or {}), "monthly_budget_usd": body.monthly_budget_usd, "budget_warn_pct": body.budget_warn_pct}
    s.commit()
    return budget.summary(s, w)


# ---------- storage ----------


@router.get("/admin/storage")
def storage(ws: Workspace = Depends(get_workspace)):
    return maintenance.usage(ws)


class StorageIn(BaseModel):
    delete_audio: bool = True
    rejected_render_days: int | None = Field(default=7, ge=0, le=3650)
    archive_after_days: int | None = Field(default=None, ge=1, le=3650)


@router.put("/admin/storage")
def set_storage(body: StorageIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    w = s.get(Workspace, ws.id, with_for_update=True)
    w.settings = {**(w.settings or {}), "storage": body.model_dump()}
    s.commit()
    return maintenance.usage(w)


@router.post("/admin/storage/clean", status_code=202)
def clean_now(s: Session = Depends(get_session)):
    j = queue.enqueue(s, maintenance.KIND, {"manual": True}, dedupe_key="maintenance", priority=50)
    s.commit()
    return {"job_id": str(j.id)}


# ---------- backups ----------


@router.get("/admin/backups")
def backups():
    st = get_settings()
    try:
        items = backup.list_backups()
    except OSError as e:
        raise HTTPException(500, f"Can't read the backup folder: {e}") from e
    return {"scheduled": bool(st.backup_dir), "keep": st.backup_keep, "folder": str(backup.backup_dir()), "items": items}


class BackupIn(BaseModel):
    media: bool = False


@router.post("/admin/backups", status_code=202)
def backup_now(body: BackupIn, s: Session = Depends(get_session)):
    j = queue.enqueue(s, maintenance.BACKUP_KIND, {"media": body.media}, dedupe_key="backup", priority=40, max_attempts=2)
    s.commit()
    return {"job_id": str(j.id)}


@router.get("/admin/backups/{name}")
def download_backup(name: str):
    try:
        p = backup.path_of(name)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(404, "Backup not found.") from e
    return FileResponse(p, media_type="application/gzip", filename=name)


# ---------- push notifications (this person's devices) ----------


@router.get("/push/key")
def push_key():
    from .. import push

    return {"public_key": push.public_key(), "kinds_default": push.DEFAULT_PUSH_KINDS}


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: PushKeys


@router.post("/push/subscriptions", status_code=201)
def push_subscribe(body: PushSubIn, request: Request, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    from .. import push
    from ..models import PushSubscription

    if p.user is None:
        raise HTTPException(409, "Sign in as a person to get push notifications.")
    try:
        push.check_endpoint(body.endpoint)
        if len(push.unb64url(body.keys.p256dh)) != 65 or len(push.unb64url(body.keys.auth)) != 16:
            raise ValueError("The browser sent keys in an unexpected format.")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    sub = s.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(user_id=p.user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth, user_agent=request.headers.get("user-agent", "")[:300])
        s.add(sub)
    else:  # same device, maybe another person now
        sub.user_id, sub.p256dh, sub.auth, sub.failures = p.user.id, body.keys.p256dh, body.keys.auth, 0
    s.commit()
    return {"ok": True, "devices": _devices(s, p.user.id)}


def _devices(s: Session, user_id) -> int:
    from ..models import PushSubscription

    return s.scalar(select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user_id)) or 0


class PushUnsubIn(BaseModel):
    endpoint: str


@router.post("/push/unsubscribe")
def push_unsubscribe(body: PushUnsubIn, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    from ..models import PushSubscription

    if p.user is not None:
        s.execute(PushSubscription.__table__.delete().where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == p.user.id))
        s.commit()
    return {"ok": True, "devices": _devices(s, p.user.id) if p.user else 0}


@router.get("/push/status")
def push_status(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    from .. import push

    prefs = (p.membership.prefs if p.membership is not None else {}) or {}
    return {"devices": _devices(s, p.user.id) if p.user else 0, "push": prefs.get("push", True), "kinds": prefs.get("push_kinds", push.DEFAULT_PUSH_KINDS)}


class PushPrefsIn(BaseModel):
    push: bool | None = None
    kinds: list[str] | None = None


@router.patch("/push/prefs")
def push_prefs(body: PushPrefsIn, s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    from ..models import Membership
    from .routes_auth import NOTIFY_KINDS

    if p.membership is None:
        raise HTTPException(409, "Sign in as a person to change push settings.")
    m = s.get(Membership, p.membership.id, with_for_update=True)
    prefs = dict(m.prefs or {})
    if body.push is not None:
        prefs["push"] = body.push
    if body.kinds is not None:
        prefs["push_kinds"] = [k for k in body.kinds if k in NOTIFY_KINDS]
    m.prefs = prefs
    s.commit()
    return push_status(s, p)


@router.post("/push/test")
def push_test(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    from .. import push

    if p.user is None:
        raise HTTPException(409, "Sign in as a person to test push.")
    if not _devices(s, p.user.id):
        raise HTTPException(409, "No device is set up for push yet. Turn push on in this browser first.")
    res = push.deliver_to_users(s, [p.user.id], {"title": "clip_star test", "body": "Push notifications work on this device.", "url": "/settings#notifications", "tag": "test"})
    s.commit()
    return res
