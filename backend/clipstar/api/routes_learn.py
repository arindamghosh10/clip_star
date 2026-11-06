"""Analytics, insights, reports and re-clipping."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..learn import insights as L
from ..learn import report as R
from ..models import Account, AccountMetric, Asset, Clip, Post, PostMetric, Report, Stage, Video, VideoStatus, Workspace
from ..pipeline.stages import enqueue_stage
from ..platforms.registry import provider_for
from .deps import get_workspace

router = APIRouter(prefix="/api", tags=["learn"])


@router.get("/analytics/overview")
def analytics_overview(days: int = Query(7, ge=1, le=90), account_id: uuid.UUID | None = None, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    if account_id is not None:
        a = s.get(Account, account_id)
        if a is None or a.workspace_id != ws.id:
            raise HTTPException(404, "Account not found.")
    return R.overview(s, ws, days=days, account_id=account_id)


@router.get("/analytics/learn")
def analytics_learn(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return R.learn_view(s, ws)


@router.post("/learn/train")
def learn_train(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    w = s.get(Workspace, ws.id, with_for_update=True)
    status = L.retrain(s, w)
    s.commit()
    return status


def _report_out(r: Report, full: bool = False) -> dict:
    out = {"id": str(r.id), "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(), "summary": r.summary, "created_at": r.created_at.isoformat()}
    if full:
        out["data"] = r.data
    return out


@router.get("/reports")
def list_reports(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return [_report_out(r) for r in s.scalars(select(Report).where(Report.workspace_id == ws.id).order_by(Report.created_at.desc()).limit(26))]


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    r = s.get(Report, report_id)
    if r is None or r.workspace_id != ws.id:
        raise HTTPException(404, "Report not found.")
    return _report_out(r, full=True)


@router.post("/reports", status_code=201)
def make_report(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    w = s.get(Workspace, ws.id, with_for_update=True)
    r = R.build_report(s, w)
    s.commit()
    return _report_out(r, full=True)


@router.get("/accounts/{account_id}/metrics")
def account_metrics(account_id: uuid.UUID, days: int = Query(30, ge=1, le=365), s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    a = s.get(Account, account_id)
    if a is None or a.workspace_id != ws.id:
        raise HTTPException(404, "Account not found.")
    prov = provider_for(a.platform.value, a.connection)
    followers = [
        {"at": m.at.isoformat(), "followers": m.followers}
        for m in s.scalars(select(AccountMetric).where(AccountMetric.account_id == a.id).order_by(AccountMetric.at.desc()).limit(days)).all()[::-1]
    ]
    return {
        "supported": prov.metrics_supported,
        "note": prov.metrics_note,
        "followers": followers,
        "updated_at": a.metrics_at.isoformat() if a.metrics_at else None,
        "overview": R.overview(s, ws, days=days, account_id=a.id),
    }


@router.get("/posts/{post_id}/metrics")
def post_metrics(post_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    p = s.get(Post, post_id)
    a = s.get(Account, p.account_id) if p else None
    if p is None or a is None or a.workspace_id != ws.id:
        raise HTTPException(404, "Post not found.")
    snaps = s.scalars(select(PostMetric).where(PostMetric.post_id == p.id).order_by(PostMetric.at))
    return {
        "latest": p.metrics or {},
        "snapshots": [
            {"at": m.at.isoformat(), "hours": m.hours, "views": m.views, "likes": m.likes, "comments": m.comments, "shares": m.shares, "saves": m.saves, "watch_pct": m.watch_pct, "follows": m.follows}
            for m in snaps
        ],
    }


@router.post("/videos/{video_id}/reclip")
def reclip(video_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Find moments again (with the current settings and learned scoring). Approved clips and clips already in posts are kept."""
    v = s.get(Video, video_id, with_for_update=True)
    if v is None or v.workspace_id != ws.id:
        raise HTTPException(404, "Video not found.")
    if v.status in (VideoStatus.queued, VideoStatus.processing):
        raise HTTPException(409, "This video is still being processed.")
    if s.scalar(select(Asset.id).where(Asset.video_id == v.id, Asset.kind == "transcript")) is None:
        raise HTTPException(409, "This video has no transcript yet. Retry processing it first.")
    v.stage = Stage.moments
    v.status = VideoStatus.queued
    v.error = None
    v.progress = 0
    enqueue_stage(s, v, Stage.moments)
    s.commit()
    kept = s.scalar(select(Clip.id).where(Clip.video_id == v.id).limit(1)) is not None
    return {"ok": True, "video_id": str(v.id), "kept_existing": kept}
