import uuid
from typing import Literal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_session
from ..errors import PermanentError
from ..publishing import service as svc
from ..pipeline.package import compose
from ..models import (
    Account,
    AccountStatus,
    Batch,
    BatchStatus,
    Clip,
    ClipStatus,
    Job,
    JobStatus,
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


@router.get("/accounts/stats")
def account_stats(s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Per account: posts published in the last 24 h, waiting, failed/unconfirmed, total published, next post time."""
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = s.execute(
        select(
            Post.account_id,
            func.count().filter(Post.status == PostStatus.published, Post.published_at >= day_ago),
            func.count().filter(Post.status.in_([PostStatus.scheduled, PostStatus.held])),
            func.count().filter(Post.status.in_([PostStatus.failed, PostStatus.unknown])),
            func.count().filter(Post.status == PostStatus.published),
            func.min(Post.scheduled_at).filter(Post.status == PostStatus.scheduled),
        )
        .join(Account, Account.id == Post.account_id)
        .where(Account.workspace_id == ws.id)
        .group_by(Post.account_id)
    )
    return {str(r[0]): {"posted_24h": r[1], "waiting": r[2], "problems": r[3], "published": r[4], "next_at": r[5].isoformat() if r[5] else None} for r in rows}


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
    data = body.model_dump(exclude_unset=True)
    if "options" in data:
        opts = {k: v for k, v in (data.pop("options") or {}).items() if v is not None}
        if "simulate" in opts and a.connection != "simulated":
            raise HTTPException(422, "Failure simulation is only for practice accounts.")
        if "board_id" in opts and a.platform == Platform.pinterest and opts["board_id"] not in [b["id"] for b in (a.options or {}).get("boards", [])]:
            raise HTTPException(422, "That board isn't on this Pinterest account.")
        a.options = {**(a.options or {}), **opts}
    if data.get("status") == AccountStatus.connected and a.connection == "oauth" and not a.token_enc:
        raise HTTPException(409, "Reconnect this account through its platform login first.")
    for k, v in data.items():
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
    clip_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    groups: list[str] = Field(default_factory=list, max_length=50)
    start_at: datetime
    spacing_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    variations: Literal["off", "ab"] = "off"


def _batch_inputs(s: Session, ws: Workspace, body: BatchIn) -> tuple[list[Clip], list[Account]]:
    if body.start_at.tzinfo is None:
        raise HTTPException(422, "start_at must include a time zone, e.g. 2026-11-07T18:00:00Z.")
    clips = list(s.scalars(select(Clip).join(Video).where(Clip.id.in_(body.clip_ids), Video.workspace_id == ws.id).order_by(Clip.score.desc())))
    if len(clips) != len(set(body.clip_ids)):
        raise HTTPException(422, "Some clips don't exist.")
    if any(c.status != ClipStatus.approved for c in clips):
        raise HTTPException(422, "Only approved clips can go into a batch.")
    q = select(Account).where(Account.workspace_id == ws.id)
    if body.account_ids and body.groups:
        q = q.where((Account.id.in_(body.account_ids)) | (Account.group_name.in_(body.groups)))
    elif body.account_ids:
        q = q.where(Account.id.in_(body.account_ids))
    elif body.groups:
        q = q.where(Account.group_name.in_(body.groups))
    else:
        raise HTTPException(422, "Pick at least one account or group.")
    accounts = list(s.scalars(q))
    if body.account_ids and len({a.id for a in accounts if a.id in set(body.account_ids)}) != len(set(body.account_ids)):
        raise HTTPException(422, "Some accounts don't exist.")
    if not accounts:
        raise HTTPException(422, "No accounts match.")
    return clips, accounts


@router.post("/batches/preview")
def preview_batch(body: BatchIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    clips, accounts = _batch_inputs(s, ws, body)
    p = svc.build_plan(s, ws, clips, accounts, body.start_at, body.spacing_minutes, body.variations)
    acc = {str(a.id): a for a in accounts}
    cl = {str(c.id): c for c in clips}
    return {
        "posts": [
            {"account_id": x.account_id, "handle": acc[x.account_id].handle, "platform": acc[x.account_id].platform.value, "timezone": acc[x.account_id].timezone, "clip_id": x.clip_id, "clip": cl[x.clip_id].title, "variant": x.variant, "at": x.at.isoformat()}
            for x in p.slots
        ],
        "warnings": p.warnings,
        "skipped": [x["reason"] for x in p.skipped],
    }


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
        origin=b.origin,
        warnings=b.warnings or [],
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
    clips, accounts = _batch_inputs(s, ws, body)
    try:
        b, _ = svc.create_batch(s, ws, body.name, clips, accounts, body.start_at, body.spacing_minutes, body.variations)
    except PermanentError as e:
        raise HTTPException(422, e.user_message) from e
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
        # approved later than planned: shift the whole plan so spacing and order are kept
        first = s.scalar(select(func.min(Post.scheduled_at)).where(Post.batch_id == b.id, Post.status == PostStatus.held))
        if first and first < b.approved_at - timedelta(minutes=5):
            s.execute(update(Post).where(Post.batch_id == b.id, Post.status == PostStatus.held).values(scheduled_at=Post.scheduled_at + (b.approved_at - first)))
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


def _post(s: Session, ws: Workspace, post_id: uuid.UUID) -> Post:
    p = s.scalar(select(Post).join(Account, Account.id == Post.account_id).where(Post.id == post_id, Account.workspace_id == ws.id).with_for_update(of=Post))
    if p is None:
        raise HTTPException(404, "Post not found.")
    return p


@router.post("/posts/{post_id}/retry", response_model=PostOut)
def retry_post(post_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Send again. For an uncertain post, only do this after checking the platform: it may already be there."""
    p = _post(s, ws, post_id)
    if p.status not in (PostStatus.failed, PostStatus.unknown):
        raise HTTPException(409, "Only failed or unconfirmed posts can be retried.")
    b = s.get(Batch, p.batch_id, with_for_update=True)
    p.status = PostStatus.scheduled if b.status in (BatchStatus.running, BatchStatus.finished) else PostStatus.held
    if b.status == BatchStatus.finished:
        b.status = BatchStatus.running
    p.scheduled_at = datetime.now(timezone.utc)
    p.last_error = None
    p.verify_attempts = 0
    s.commit()
    return p


@router.post("/posts/{post_id}/cancel", response_model=PostOut)
def cancel_post(post_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    p = _post(s, ws, post_id)
    if p.status not in (PostStatus.held, PostStatus.scheduled, PostStatus.failed, PostStatus.unknown):
        raise HTTPException(409, "This post is already out or being published.")
    p.status = PostStatus.cancelled
    svc.finish_batch_if_done(s, p.batch_id)
    s.commit()
    return p


class RescheduleIn(BaseModel):
    scheduled_at: datetime
    force: bool = False  # move even if it breaks a posting rule (the warnings were shown)


@router.post("/posts/{post_id}/reschedule")
def reschedule_post(post_id: uuid.UUID, body: RescheduleIn, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """Move one waiting post to another time. Breaking a posting rule needs force=true (answer 409 lists the reasons)."""
    from ..publishing.scheduler import check_move

    p = s.scalar(select(Post).join(Account, Account.id == Post.account_id).where(Post.id == post_id, Account.workspace_id == ws.id).with_for_update(of=Post))
    if p is None:
        raise HTTPException(404, "Post not found.")
    if p.status not in (PostStatus.held, PostStatus.scheduled):
        raise HTTPException(409, "Only posts that haven't gone out yet can be moved.")
    at = body.scheduled_at if body.scheduled_at.tzinfo else body.scheduled_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if at < now + timedelta(minutes=2):
        raise HTTPException(422, "Pick a time at least 2 minutes from now.")
    if s.scalar(select(Job.id).where(Job.dedupe_key == f"post:{p.id}:publish", Job.status.in_([JobStatus.queued, JobStatus.running])).limit(1)):
        raise HTTPException(409, "This post is being sent right now and can't be moved.")
    a = s.get(Account, p.account_id)
    st = ws.settings or {}
    info = svc.account_info(a)
    active = (PostStatus.held, PostStatus.scheduled, PostStatus.publishing, PostStatus.published)
    taken = [x for (x,) in s.execute(select(func.coalesce(Post.published_at, Post.scheduled_at)).where(Post.account_id == a.id, Post.id != p.id, Post.status.in_(active)))]
    same = [x for (x,) in s.execute(select(func.coalesce(Post.published_at, Post.scheduled_at)).where(Post.clip_id == p.clip_id, Post.account_id != a.id, Post.status.in_(active)))]
    warnings = check_move(info, at, taken, 60, bool(st.get("quiet_hours", True)), same, int(st.get("spacing_minutes", 45)))
    if warnings and not body.force:
        raise HTTPException(409, {"message": "This time breaks a posting rule.", "warnings": warnings})
    p.scheduled_at = at
    p.last_error = ("Moved by hand: " + " ".join(warnings)) if warnings else None
    s.commit()
    return {"post": PostOut.model_validate(p).model_dump(mode="json"), "warnings": warnings}


@router.post("/posts/{post_id}/mark-published", response_model=PostOut)
def mark_published(post_id: uuid.UUID, s: Session = Depends(get_session), ws: Workspace = Depends(get_workspace)):
    """For an unconfirmed post you found on the platform."""
    p = _post(s, ws, post_id)
    if p.status not in (PostStatus.unknown, PostStatus.failed):
        raise HTTPException(409, "Only unconfirmed or failed posts can be marked as published.")
    p.status = PostStatus.published
    p.published_at = datetime.now(timezone.utc)
    p.last_error = "Marked as published by you."
    svc.finish_batch_if_done(s, p.batch_id)
    s.commit()
    return p


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
