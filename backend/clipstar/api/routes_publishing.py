import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_session
from ..pipeline.package import compose
from ..models import (
    Account,
    Batch,
    BatchStatus,
    Clip,
    ClipStatus,
    Platform,
    Post,
    PostStatus,
    Rule,
    Video,
    Workspace,
)
from .deps import get_workspace
from .schemas import AccountIn, AccountOut, AccountPatch, BatchOut, PostOut, RuleIn, RuleOut, RulePatch

router = APIRouter(prefix="/api", tags=["publishing"])


# ---------- accounts ----------


def _account(s: Session, ws: Workspace, account_id: uuid.UUID) -> Account:
    a = s.get(Account, account_id)
    if a is None or a.workspace_id != ws.id:
        raise HTTPException(404, "Account not found.")
    return a


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(platform: Platform | None = None, group: str | None = None, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    q = select(Account).where(Account.workspace_id == ws.id)
    if platform:
        q = q.where(Account.platform == platform)
    if group:
        q = q.where(Account.group_name == group)
    return list(s.scalars(q.order_by(Account.platform, Account.handle)))


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    a = Account(workspace_id=ws.id, **body.model_dump())
    s.add(a)
    try:
        s.commit()
    except IntegrityError as e:
        s.rollback()
        raise HTTPException(409, f"{body.handle} on {body.platform.value} is already connected.") from e
    return a


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: uuid.UUID, body: AccountPatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    a = _account(s, ws, account_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    s.commit()
    return a


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    a = _account(s, ws, account_id)
    busy = s.scalar(select(func.count()).select_from(Post).where(Post.account_id == a.id, Post.status == PostStatus.publishing))
    if busy:
        raise HTTPException(409, "A post is being published from this account right now. Try again in a minute.")
    s.delete(a)
    s.commit()


# ---------- batches ----------


class BatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    clip_ids: list[uuid.UUID] = Field(min_length=1)
    account_ids: list[uuid.UUID] = Field(min_length=1)
    start_at: datetime
    spacing_minutes: int = Field(default=45, ge=0, le=24 * 60)
    variations: str = Field(default="off", max_length=64)


def _batch_out(s: Session, b: Batch) -> BatchOut:
    row = s.execute(
        select(
            func.count(),
            func.count().filter(Post.status == PostStatus.published),
            func.count(func.distinct(Post.account_id)),
            func.count(func.distinct(Post.clip_id)),
        ).where(Post.batch_id == b.id)
    ).one()
    return BatchOut(
        id=b.id,
        name=b.name,
        status=b.status,
        variations=b.variations,
        approved_at=b.approved_at,
        created_at=b.created_at,
        posts=row[0],
        posted=row[1],
        accounts=row[2],
        clips=row[3],
    )


def _batch(s: Session, ws: Workspace, batch_id: uuid.UUID) -> Batch:
    b = s.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
    if b is None or b.workspace_id != ws.id:
        raise HTTPException(404, "Batch not found.")
    return b


@router.get("/batches", response_model=list[BatchOut])
def list_batches(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return [_batch_out(s, b) for b in s.scalars(select(Batch).where(Batch.workspace_id == ws.id).order_by(Batch.created_at.desc()))]


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    if body.start_at.tzinfo is None:
        raise HTTPException(422, "start_at must include a time zone, e.g. 2026-11-07T18:00:00Z.")
    clips = list(s.scalars(select(Clip).join(Video).where(Clip.id.in_(body.clip_ids), Video.workspace_id == ws.id)))
    if len(clips) != len(set(body.clip_ids)):
        raise HTTPException(422, "Some clips don't exist.")
    if any(c.status != ClipStatus.approved for c in clips):
        raise HTTPException(422, "Only approved clips can go into a batch.")
    accounts = list(s.scalars(select(Account).where(Account.id.in_(body.account_ids), Account.workspace_id == ws.id)))
    if len(accounts) != len(set(body.account_ids)):
        raise HTTPException(422, "Some accounts don't exist.")
    b = Batch(workspace_id=ws.id, name=body.name, variations=body.variations)
    s.add(b)
    s.flush()
    # Simple schedule: clips one after another, accounts spaced apart. The full scheduler
    # (daily caps, posting hours, time zones) replaces this in the Publish phase.
    t = body.start_at.astimezone(timezone.utc)
    for clip in clips:
        for acc in accounts:
            c = (clip.copy or {}).get(acc.platform.value)
            caption = compose(c, acc.platform.value) if isinstance(c, dict) else (c if isinstance(c, str) else clip.title)
            s.add(Post(batch_id=b.id, account_id=acc.id, clip_id=clip.id, caption=caption, scheduled_at=t, status=PostStatus.held))
            t += timedelta(minutes=body.spacing_minutes)
    s.commit()
    return _batch_out(s, b)


_TRANSITIONS = {
    "approve": ({BatchStatus.awaiting}, BatchStatus.running, PostStatus.held, PostStatus.scheduled),
    "disable": ({BatchStatus.running}, BatchStatus.disabled, PostStatus.scheduled, PostStatus.held),
    "enable": ({BatchStatus.disabled}, BatchStatus.running, PostStatus.held, PostStatus.scheduled),
}


@router.post("/batches/{batch_id}/{action}", response_model=BatchOut)
def batch_action(batch_id: uuid.UUID, action: str, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    b = _batch(s, ws, batch_id)
    if action == "cancel":
        if b.status in (BatchStatus.finished, BatchStatus.cancelled):
            raise HTTPException(409, "This batch is already finished.")
        b.status = BatchStatus.cancelled
        s.execute(update(Post).where(Post.batch_id == b.id, Post.status.in_([PostStatus.held, PostStatus.scheduled])).values(status=PostStatus.cancelled))
        s.commit()
        return _batch_out(s, b)
    if action not in _TRANSITIONS:
        raise HTTPException(404, "Unknown action. Use approve, disable, enable or cancel.")
    allowed, new, from_post, to_post = _TRANSITIONS[action]
    if b.status not in allowed:
        raise HTTPException(409, f"Can't {action} a batch that is {b.status.value}.")
    b.status = new
    if action == "approve":
        b.approved_at = datetime.now(timezone.utc)
    # Posts already publishing are not touched; the publisher re-checks the batch right before posting.
    s.execute(update(Post).where(Post.batch_id == b.id, Post.status == from_post).values(status=to_post))
    s.commit()
    return _batch_out(s, b)


# ---------- posts ----------


@router.get("/posts", response_model=list[PostOut])
def list_posts(
    account_id: uuid.UUID | None = None,
    platform: Platform | None = None,
    group: str | None = None,
    clip_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    status: PostStatus | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    s: Session = Depends(get_session),
    ws: Workspace = Depends(get_workspace),
):
    q = select(Post).join(Account, Account.id == Post.account_id).where(Account.workspace_id == ws.id)
    if account_id:
        q = q.where(Post.account_id == account_id)
    if platform:
        q = q.where(Account.platform == platform)
    if group:
        q = q.where(Account.group_name == group)
    if clip_id:
        q = q.where(Post.clip_id == clip_id)
    if batch_id:
        q = q.where(Post.batch_id == batch_id)
    if status:
        q = q.where(Post.status == status)
    return list(s.scalars(q.order_by(Post.scheduled_at.desc()).limit(limit).offset(offset)))


# ---------- rules ----------


def _rule(s: Session, ws: Workspace, rule_id: uuid.UUID) -> Rule:
    r = s.get(Rule, rule_id)
    if r is None or r.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found.")
    return r


@router.get("/rules", response_model=list[RuleOut])
def list_rules(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    return list(s.scalars(select(Rule).where(Rule.workspace_id == ws.id).order_by(Rule.created_at)))


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    r = Rule(workspace_id=ws.id, **body.model_dump())
    s.add(r)
    s.commit()
    return r


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RulePatch, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    r = _rule(s, ws, rule_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    s.commit()
    return r


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    s.delete(_rule(s, ws, rule_id))
    s.commit()
