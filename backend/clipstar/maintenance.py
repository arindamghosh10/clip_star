"""Daily housekeeping: free disk space by policy, purge old records, warn when disk is low, run scheduled backups.

Storage policy (workspace settings, owner only):
- audio extracts are deleted once a video is ready (they're only used for transcription);
- renders of rejected clips are deleted after `rejected_render_days` (default 7);
- with `archive_after_days` set, the original and preview of ready videos older than that are deleted
  once no clip of theirs is waiting to be posted. Rendered clips, transcripts and stats stay; such a video
  can't be re-edited or re-clipped any more.
Nothing is deleted while a video is being processed or has active jobs.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from .config import get_settings
from .db import session_scope
from .jobs import queue
from .jobs.runtime import Handler, JobContext, register
from .models import (
    Asset,
    Batch,
    Clip,
    ClipStatus,
    Event,
    Job,
    JobStatus,
    Notification,
    OAuthState,
    Post,
    PostStatus,
    UserSession,
    Video,
    VideoStatus,
    Workspace,
)
from .storage import get_storage

log = logging.getLogger("clipstar.maintenance")
KIND = "maintenance.run"
BACKUP_KIND = "backup.run"
LOW_DISK_GB = 5.0
DEFAULTS = {"rejected_render_days": 7, "archive_after_days": None, "delete_audio": True}


def now() -> datetime:
    return datetime.now(timezone.utc)


def policy(ws: Workspace) -> dict:
    p = dict(DEFAULTS)
    p.update({k: v for k, v in ((ws.settings or {}).get("storage") or {}).items() if k in DEFAULTS})
    return p


def _rm(rel: str | None) -> int:
    if not rel:
        return 0
    try:
        p = get_storage().abs(rel)
        if p.is_file():
            n = p.stat().st_size
            p.unlink()
            return n
    except (OSError, ValueError):
        log.warning("couldn't delete %s", rel)
    return 0


def _busy(s, vid: uuid.UUID) -> bool:
    return bool(s.scalar(select(Job.id).where(Job.video_id == vid, Job.status.in_([JobStatus.queued, JobStatus.running])).limit(1)))


def clean_storage(s, ws: Workspace) -> dict:
    pol = policy(ws)
    freed = {"audio": 0, "rejected_renders": 0, "archived": 0}
    videos = list(s.scalars(select(Video).where(Video.workspace_id == ws.id, Video.status == VideoStatus.ready)))
    for v in videos:
        if _busy(s, v.id):
            continue
        assets = {a.kind: a for a in s.scalars(select(Asset).where(Asset.video_id == v.id))}
        if pol["delete_audio"] and "audio" in assets:
            freed["audio"] += _rm(assets["audio"].path)
            s.delete(assets["audio"])
        days = pol["archive_after_days"]
        if isinstance(days, int) and days > 0 and v.created_at < now() - timedelta(days=days) and not (v.meta or {}).get("archived"):
            waiting = s.scalar(
                select(Post.id).join(Clip, Clip.id == Post.clip_id).where(Clip.video_id == v.id, Post.status.in_([PostStatus.held, PostStatus.scheduled, PostStatus.publishing, PostStatus.unknown])).limit(1)
            )
            pending = s.scalar(select(Clip.id).where(Clip.video_id == v.id, Clip.status == ClipStatus.pending).limit(1))
            if not waiting and not pending:
                for kind in ("master", "proxy", "audio"):
                    if kind in assets and assets[kind] in s:
                        freed["archived"] += _rm(assets[kind].path)
                        s.delete(assets[kind])
                v.meta = {**(v.meta or {}), "archived": now().isoformat()}
    rdays = pol["rejected_render_days"]
    if isinstance(rdays, int) and rdays >= 0:
        old = now() - timedelta(days=rdays)
        for c in s.scalars(select(Clip).join(Video, Video.id == Clip.video_id).where(Video.workspace_id == ws.id, Clip.status == ClipStatus.rejected, Clip.updated_at < old)):
            renders = (c.meta or {}).get("renders") or {}
            if not renders or s.scalar(select(Post.id).where(Post.clip_id == c.id).limit(1)):
                continue
            for r in renders.values():
                freed["rejected_renders"] += _rm(r.get("path")) + _rm(r.get("cover"))
            c.meta = {**(c.meta or {}), "renders": {}, "renders_deleted": now().isoformat()}
    return freed


def purge_records(s) -> dict:
    out = {}
    out["jobs"] = s.execute(delete(Job).where(Job.status.in_([JobStatus.succeeded, JobStatus.cancelled]), Job.finished_at < now() - timedelta(days=30))).rowcount
    out["failed_jobs"] = s.execute(delete(Job).where(Job.status == JobStatus.failed, Job.finished_at < now() - timedelta(days=90))).rowcount
    out["sessions"] = s.execute(delete(UserSession).where(UserSession.expires_at < now())).rowcount
    out["oauth_states"] = s.execute(delete(OAuthState).where(OAuthState.created_at < now() - timedelta(days=1))).rowcount
    out["notifications"] = s.execute(delete(Notification).where(Notification.created_at < now() - timedelta(days=90))).rowcount
    # the event feed keeps 30 days (deliveries go with their events)
    out["events"] = s.execute(delete(Event).where(Event.created_at < now() - timedelta(days=30), Event.fanned_out.is_(True))).rowcount
    return out


def clean_temp_files(older_than_s: int = 86400) -> int:
    root = get_storage().root
    n = 0
    cutoff = time.time() - older_than_s
    for p in root.rglob(".tmp-*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def usage(ws: Workspace | None = None) -> dict:
    """Bytes on disk by kind of file."""
    root = get_storage().root
    kinds = {"originals": 0, "previews": 0, "clips": 0, "audio": 0, "analysis": 0, "backups": 0, "other": 0}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = p.relative_to(root).parts
            if rel and rel[0] == "backups":
                kinds["backups"] += size
            elif "clips" in rel:
                kinds["clips"] += size
            elif f.startswith("master"):
                kinds["originals"] += size
            elif f.startswith("proxy"):
                kinds["previews"] += size
            elif f.startswith("audio"):
                kinds["audio"] += size
            elif f.endswith((".json", ".srt", ".vtt")):
                kinds["analysis"] += size
            else:
                kinds["other"] += size
    st = get_storage()
    return {"by_kind": kinds, "total_bytes": sum(kinds.values()), "free_bytes": st.free_bytes(), "low_disk_gb": LOW_DISK_GB, "policy": policy(ws) if ws else DEFAULTS}


def run(ctx: JobContext | None = None) -> dict:
    from .notify import notify

    result: dict = {}
    with session_scope() as s:
        for ws in s.scalars(select(Workspace)):
            result[str(ws.id)] = clean_storage(s, ws)
    with session_scope() as s:
        result["purged"] = purge_records(s)
    result["temp_files"] = clean_temp_files()
    free_gb = get_storage().free_bytes() / 1024**3
    if free_gb < LOW_DISK_GB:
        with session_scope() as s:
            for (wid,) in s.execute(select(Workspace.id)):
                notify(s, wid, "storage", f"Disk space is low ({free_gb:.1f} GB free)", "Processing and rendering may fail. Delete old videos or turn on automatic archiving in Settings → Storage.", "/settings", "warn", dedupe=f"storage:{wid}:{now():%Y-%m-%d}")
    if get_settings().backup_dir:
        with session_scope() as s:
            queue.enqueue(s, BACKUP_KIND, {"scheduled": True}, dedupe_key="backup", priority=95, max_attempts=2)
    return result


def _size(n: int) -> str:
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{n / 1024**2:.1f} MB" if n >= 1024**2 else f"{max(1, n // 1024)} KB"


def run_backup(ctx: JobContext) -> dict:
    from . import backup
    from .notify import notify

    p = backup.create(media=bool(ctx.payload.get("media")))
    removed = backup.prune(get_settings().backup_keep)
    if not ctx.payload.get("scheduled"):
        with session_scope() as s:
            for (wid,) in s.execute(select(Workspace.id)):
                notify(s, wid, "backup", "Backup finished", f"{p.name} ({_size(p.stat().st_size)}).", "/settings", dedupe=f"backup:{p.name}")
    return {"file": p.name, "pruned": removed}


def _backup_failed(s, job: Job) -> None:
    from .notify import notify

    for (wid,) in s.execute(select(Workspace.id)):
        notify(s, wid, "backup", "Backup failed", job.last_error or "See Activity for details.", "/activity", "error", dedupe=f"backup_failed:{job.id}")


def dispatch_maintenance() -> bool:
    """Queue the daily run unless one finished in the last 20 hours."""
    with session_scope() as s:
        recent = s.scalar(select(Job.id).where(Job.kind == KIND, Job.created_at > now() - timedelta(hours=20)).limit(1))
        if recent:
            return False
        queue.enqueue(s, KIND, {}, dedupe_key="maintenance", priority=95)
        return True


def register_handlers() -> None:
    register(KIND, Handler(run=lambda ctx: run(ctx)))
    register(BACKUP_KIND, Handler(run=run_backup, on_failure=_backup_failed))
