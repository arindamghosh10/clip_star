"""The workspace's music library: tracks the creator owns or has a licence for."""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..errors import ClipstarError
from ..models import Clip, ClipStatus, MusicTrack, Video, Workspace
from ..pipeline.music import ALLOWED, MAX_BYTES, import_track
from ..storage import get_storage
from .deps import authorize, get_workspace

router = APIRouter(prefix="/api", tags=["music"], dependencies=[Depends(authorize)])


def _out(t: MusicTrack, used: int = 0) -> dict:
    return {"id": str(t.id), "title": t.title, "duration_s": round(t.duration_s, 1), "size_bytes": t.size_bytes, "license_note": t.license_note, "used_by": used, "created_at": t.created_at.isoformat() if t.created_at else None}


def _usage(s: Session, ws: Workspace) -> dict[str, int]:
    used: dict[str, int] = {}
    for (variants,) in s.execute(select(Clip.variants).join(Video, Video.id == Clip.video_id).where(Video.workspace_id == ws.id, Clip.status != ClipStatus.rejected)):
        for v in variants or []:
            tid = (v.get("music") or {}).get("track_id")
            if tid:
                used[tid] = used.get(tid, 0) + 1
    return used


@router.get("/music")
def list_music(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    used = _usage(s, ws)
    return [_out(t, used.get(str(t.id), 0)) for t in s.scalars(select(MusicTrack).where(MusicTrack.workspace_id == ws.id).order_by(MusicTrack.created_at.desc()))]


@router.post("/music", status_code=201)
async def upload_music(
    file: UploadFile = File(...),
    title: str = Form(""),
    license_note: str = Form(""),
    confirm_rights: bool = Form(False),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    if not confirm_rights:
        raise HTTPException(422, "Confirm that you own this music or have a licence to use it in your videos.")
    name = file.filename or "track"
    if Path(name).suffix.lower() not in ALLOWED:
        raise HTTPException(422, "Use an MP3, M4A, AAC, WAV, OGG, OPUS or FLAC file.")
    tid = uuid.uuid4()
    st = get_storage()
    rel = f"music/{ws.id}/{tid}.m4a"
    with tempfile.TemporaryDirectory(prefix="clipstar-music-") as tmp:
        src = Path(tmp) / f"in{Path(name).suffix.lower()}"
        size = 0
        with src.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(422, "The track is larger than 50 MB.")
                f.write(chunk)
        try:
            dur = import_track(src, st.abs(rel))
        except ClipstarError as e:
            raise HTTPException(422, e.user_message) from e
    t = MusicTrack(id=tid, workspace_id=ws.id, title=(title.strip() or Path(name).stem)[:200], path=rel, duration_s=dur, size_bytes=st.abs(rel).stat().st_size, license_note=license_note.strip()[:500])
    s.add(t)
    s.commit()
    return _out(t)


def _track(s: Session, ws: Workspace, track_id: uuid.UUID) -> MusicTrack:
    t = s.get(MusicTrack, track_id)
    if t is None or t.workspace_id != ws.id:
        raise HTTPException(404, "Track not found.")
    return t


@router.get("/music/{track_id}/audio")
def music_audio(track_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    t = _track(s, ws, track_id)
    return FileResponse(get_storage().abs(t.path), media_type="audio/mp4", headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/music/{track_id}", status_code=204)
def delete_music(track_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    t = _track(s, ws, track_id)
    n = _usage(s, ws).get(str(t.id), 0)
    if n:
        raise HTTPException(409, f"{n} clip version{'s use' if n != 1 else ' uses'} this track. Choose other music for them first.")
    w = s.get(Workspace, ws.id, with_for_update=True)
    if (w.settings or {}).get("default_music_id") == str(t.id):
        w.settings = {**w.settings, "default_music_id": None}
    s.delete(t)
    s.commit()
    get_storage().abs(t.path).unlink(missing_ok=True)
