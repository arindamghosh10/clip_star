"""Notifications, spending limits, storage and backups."""

from fastapi import APIRouter, Depends, HTTPException
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
    seen = p.user.notifications_seen_at if p.user else None
    items = list(s.scalars(select(Notification).where(Notification.workspace_id == ws.id).order_by(Notification.created_at.desc()).limit(max(1, min(limit, 100)))))
    unread = s.scalar(select(func.count(Notification.id)).where(Notification.workspace_id == ws.id, *( [Notification.created_at > seen] if seen else [] ))) or 0
    return {"unread": unread, "items": [_n_out(n, seen) for n in items]}


@router.post("/notifications/seen")
def mark_seen(s: Session = Depends(get_session), p: auth.Principal = Depends(principal)):
    if p.user is None:
        return {"ok": True}
    u = s.get(User, p.user.id, with_for_update=True)
    u.notifications_seen_at = func.now()
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
