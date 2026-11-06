import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..engage import service as eng
from ..jobs import queue
from ..models import Account, Clip, Comment, CommentCategory, Platform, Post, ReplyStatus, Workspace
from ..platforms.registry import provider_for
from .deps import get_workspace

router = APIRouter(prefix="/api", tags=["engage"])


def _out(cm: Comment, a: Account, clip_title: str | None) -> dict:
    return {
        "id": str(cm.id),
        "account_id": str(a.id),
        "handle": a.handle,
        "platform": a.platform.value,
        "practice": a.connection == "simulated",
        "post_id": str(cm.post_id) if cm.post_id else None,
        "clip_title": clip_title,
        "author": cm.author,
        "message": cm.message,
        "commented_at": cm.commented_at.isoformat() if cm.commented_at else None,
        "category": cm.category.value,
        "category_by": cm.category_by,
        "state": cm.state,
        "draft": cm.draft,
        "draft_by": cm.draft_by,
        "reply_text": cm.reply_text,
        "reply_status": cm.reply_status.value,
        "reply_auto": cm.reply_auto,
        "replied_at": cm.replied_at.isoformat() if cm.replied_at else None,
        "hidden": cm.hidden,
        "error": cm.error,
        "max_chars": provider_for(a.platform.value, a.connection).reply_max_chars,
    }


def _comment(s: Session, ws: Workspace, cid: uuid.UUID) -> tuple[Comment, Account]:
    row = s.execute(select(Comment, Account).join(Account, Account.id == Comment.account_id).where(Comment.id == cid, Account.workspace_id == ws.id).with_for_update(of=Comment)).first()
    if row is None:
        raise HTTPException(404, "Comment not found.")
    return row[0], row[1]


def _with_clip(s: Session, cm: Comment, a: Account) -> dict:
    title = None
    if cm.post_id:
        title = s.scalar(select(Clip.title).join(Post, Post.clip_id == Clip.id).where(Post.id == cm.post_id))
    return _out(cm, a, title)


@router.get("/comments")
def list_comments(
    state: Literal["open", "done", "all"] = "open",
    category: CommentCategory | None = None,
    account_id: uuid.UUID | None = None,
    platform: Platform | None = None,
    limit: int = Query(300, ge=1, le=1000),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    q = (
        select(Comment, Account, Clip.title)
        .join(Account, Account.id == Comment.account_id)
        .outerjoin(Post, Post.id == Comment.post_id)
        .outerjoin(Clip, Clip.id == Post.clip_id)
        .where(Account.workspace_id == ws.id)
    )
    if state != "all":
        q = q.where(Comment.state == state)
    if category:
        q = q.where(Comment.category == category)
    if account_id:
        q = q.where(Comment.account_id == account_id)
    if platform:
        q = q.where(Account.platform == platform)
    rows = s.execute(q.order_by(Comment.commented_at.desc().nullslast(), Comment.created_at.desc()).limit(limit)).all()
    return [_out(c, a, t) for c, a, t in rows]


@router.get("/comments/summary")
def summary(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    counts = dict(
        s.execute(
            select(Comment.category, func.count()).join(Account, Account.id == Comment.account_id).where(Account.workspace_id == ws.id, Comment.state == "open").group_by(Comment.category)
        ).all()
    )
    attention = s.scalar(
        select(func.count()).select_from(Comment).join(Account, Account.id == Comment.account_id).where(Account.workspace_id == ws.id, Comment.reply_status.in_([ReplyStatus.failed, ReplyStatus.unknown]))
    )
    accounts = []
    for a in s.scalars(select(Account).where(Account.workspace_id == ws.id).order_by(Account.platform, Account.handle)):
        prov = provider_for(a.platform.value, a.connection)
        accounts.append({"id": str(a.id), "handle": a.handle, "platform": a.platform.value, "supported": prov.comments_supported, "note": None if prov.comments_supported else prov.comments_note, "synced_at": a.comments_synced_at.isoformat() if a.comments_synced_at else None})
    return {"open": {k.value: v for k, v in counts.items()}, "needs_attention": attention, "accounts": accounts}


class CommentPatch(BaseModel):
    category: CommentCategory | None = None
    draft: str | None = Field(default=None, max_length=10000)


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: uuid.UUID, body: CommentPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    cm, a = _comment(s, ws, comment_id)
    if body.category is not None and body.category != cm.category:
        cm.category = body.category
        cm.category_by = "user"
    if body.draft is not None:
        cm.draft = body.draft
        cm.draft_by = "user"
    s.commit()
    return _with_clip(s, cm, a)


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    confirm_resend: bool = False  # needed when the last attempt is unconfirmed


@router.post("/comments/{comment_id}/send")
def send_reply(comment_id: uuid.UUID, body: SendIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    cm, a = _comment(s, ws, comment_id)
    prov = provider_for(a.platform.value, a.connection)
    if not prov.comments_supported:
        raise HTTPException(409, prov.comments_note)
    text = body.text.strip()
    if len(text) > prov.reply_max_chars:
        raise HTTPException(422, f"Replies on {a.platform.value} can be at most {prov.reply_max_chars} characters.")
    if cm.reply_status in (ReplyStatus.queued, ReplyStatus.sending):
        raise HTTPException(409, "A reply to this comment is already being sent.")
    if cm.reply_status == ReplyStatus.sent:
        raise HTTPException(409, "You already replied to this comment.")
    if cm.reply_status == ReplyStatus.unknown and not body.confirm_resend:
        raise HTTPException(409, "The last reply may already be posted. Check the platform, then confirm to send again.")
    cm.reply_text = text
    cm.reply_status = ReplyStatus.queued
    cm.reply_auto = False
    cm.state = "done"
    cm.error = None
    eng.enqueue_reply(s, cm)
    s.commit()
    return _with_clip(s, cm, a)


def _set(s: Session, ws: Workspace, comment_id: uuid.UUID, **kw) -> dict:
    cm, a = _comment(s, ws, comment_id)
    for k, v in kw.items():
        setattr(cm, k, v)
    s.commit()
    return _with_clip(s, cm, a)


@router.post("/comments/{comment_id}/skip")
def skip(comment_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _set(s, ws, comment_id, state="done")


@router.post("/comments/{comment_id}/reopen")
def reopen(comment_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return _set(s, ws, comment_id, state="open")


@router.post("/comments/{comment_id}/mark-sent")
def mark_sent(comment_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    cm, a = _comment(s, ws, comment_id)
    if cm.reply_status not in (ReplyStatus.unknown, ReplyStatus.failed):
        raise HTTPException(409, "Only unconfirmed or failed replies can be marked as sent.")
    cm.reply_status = ReplyStatus.sent
    cm.replied_at = datetime.now(timezone.utc)
    cm.state = "done"
    cm.error = "Marked as sent by you."
    s.commit()
    return _with_clip(s, cm, a)


@router.post("/comments/{comment_id}/{action}")
def hide_or_unhide(comment_id: uuid.UUID, action: Literal["hide", "unhide"], s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    cm, a = _comment(s, ws, comment_id)
    prov = provider_for(a.platform.value, a.connection)
    if not prov.comments_supported:
        raise HTTPException(409, prov.comments_note)
    hidden = action == "hide"
    queue.enqueue(s, eng.HIDE_KIND, {"comment_id": str(cm.id), "hidden": hidden}, dedupe_key=f"comment:{cm.id}:{action}")
    if hidden:
        cm.state = "done"
    s.commit()
    return _with_clip(s, cm, a)


@router.post("/comments/sync")
def sync_now(ws: Workspace = Depends(get_workspace)):
    return {"queued": eng.dispatch_sync(force_workspace=ws.id)}
