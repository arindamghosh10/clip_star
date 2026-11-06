"""Request/response shapes for the REST API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import (
    AccountStatus,
    BatchStatus,
    ClipStatus,
    JobStatus,
    Platform,
    PostStatus,
    Stage,
    VideoStatus,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- videos ----------


class AssetOut(ORM):
    kind: str
    size_bytes: int
    meta: dict


class VideoOut(ORM):
    id: uuid.UUID
    title: str
    source_filename: str
    status: VideoStatus
    stage: Stage
    progress: int
    duration_s: float | None
    size_bytes: int
    meta: dict
    error: str | None
    created_at: datetime
    updated_at: datetime
    clips: int = 0
    active_job_id: uuid.UUID | None = None


class VideoDetail(VideoOut):
    assets: list[AssetOut] = []


class VideoPatch(BaseModel):
    title: str = Field(min_length=1, max_length=300)


# ---------- clips ----------


class ClipOut(ORM):
    id: uuid.UUID
    video_id: uuid.UUID
    title: str
    start_s: float
    end_s: float
    score: int
    reason: str
    hook: str
    status: ClipStatus
    copy_: dict = Field(alias="copy", serialization_alias="copy")
    variants: list
    engine: str
    meta: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PlatformCopy(BaseModel):
    title: str = Field(default="", max_length=300)
    caption: str = Field(default="", max_length=6000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class VariantIn(BaseModel):
    id: Literal["A", "B"]
    caption_style: Literal["bold-pop", "clean"] = "bold-pop"
    hook: str = Field(default="", max_length=60)


class ClipPatch(BaseModel):
    status: ClipStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    hook: str | None = Field(default=None, max_length=200)
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    variants: list[VariantIn] | None = Field(default=None, min_length=1, max_length=2)
    copy_: dict[str, PlatformCopy] | None = Field(default=None, alias="copy")

    model_config = ConfigDict(populate_by_name=True)


class TranscriptReplace(BaseModel):
    find: str = Field(min_length=1, max_length=100)
    replace: str = Field(max_length=100)
    match_case: bool = False


class WorkspaceSettingsIn(BaseModel):
    """Every key is optional; only the ones sent are changed."""

    model_config = ConfigDict(extra="forbid")

    niche: str | None = Field(default=None, max_length=500)
    voice: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, max_length=500)
    banned_topics: list[Annotated[str, Field(max_length=60)]] | None = Field(default=None, max_length=50)
    hashtags: list[Annotated[str, Field(max_length=50)]] | None = Field(default=None, max_length=10)
    cta: str | None = Field(default=None, max_length=150)
    clip_min_s: float | None = Field(default=None, ge=5, le=170)
    clip_max_s: float | None = Field(default=None, ge=10, le=180)
    clip_target_s: float | None = Field(default=None, ge=5, le=180)
    max_clips: int | None = Field(default=None, ge=1, le=30)
    variants: Literal[1, 2] | None = None
    caption_style: Literal["bold-pop", "clean"] | None = None
    platforms: list[Platform] | None = Field(default=None, min_length=1)
    auto_approve_score: int | None = Field(default=None, ge=1, le=100)
    spacing_minutes: int | None = Field(default=None, ge=0, le=1440)
    duplicate_warning_accounts: int | None = Field(default=None, ge=1, le=500)
    quiet_hours: bool | None = None


class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: WorkspaceSettingsIn | None = None


# ---------- accounts ----------

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"Unknown time zone '{v}'. Use a name like 'Europe/London'.") from e
    return v


def validate_hhmm(v: str) -> str:
    if not _HHMM.match(v):
        raise ValueError("Use 24-hour HH:MM, e.g. 09:30.")
    return v


class AccountIn(BaseModel):
    platform: Platform
    handle: str = Field(min_length=1, max_length=200)
    group_name: str = Field(default="", max_length=100)
    timezone: str = "UTC"
    language: str = Field(default="English", max_length=64)
    daily_cap: int = Field(default=10, ge=1, le=500)
    posting_start: str = "09:00"
    posting_end: str = "21:00"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        return validate_tz(v)

    @field_validator("posting_start", "posting_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        return validate_hhmm(v)


class AccountOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: str | None = Field(default=None, max_length=100)  # Pinterest
    privacy: str | None = Field(default=None, max_length=40)  # YouTube: public|unlisted|private; TikTok: PUBLIC_TO_EVERYONE|SELF_ONLY|...
    simulate: Literal["ok", "fail_once", "fail", "timeout", "expired"] | None = None  # practice accounts only


class AccountPatch(BaseModel):
    group_name: str | None = Field(default=None, max_length=100)
    status: AccountStatus | None = None
    timezone: str | None = None
    language: str | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=500)
    posting_start: str | None = None
    posting_end: str | None = None
    handle: str | None = Field(default=None, min_length=1, max_length=200)
    options: AccountOptions | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return v if v is None else validate_tz(v)

    @field_validator("posting_start", "posting_end")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        return v if v is None else validate_hhmm(v)


class AccountOut(ORM):
    id: uuid.UUID
    platform: Platform
    handle: str
    group_name: str
    status: AccountStatus
    timezone: str
    language: str
    daily_cap: int
    posting_start: str
    posting_end: str
    connection: str
    remote_id: str | None
    token_expires_at: datetime | None
    options: dict
    last_error: str | None
    created_at: datetime


# ---------- batches & posts ----------


class BatchOut(ORM):
    id: uuid.UUID
    name: str
    origin: str = "manual"
    warnings: list = []
    status: BatchStatus
    variations: str
    approved_at: datetime | None
    created_at: datetime
    posts: int = 0
    posted: int = 0
    accounts: int = 0
    clips: int = 0


class PostOut(ORM):
    id: uuid.UUID
    batch_id: uuid.UUID
    account_id: uuid.UUID
    clip_id: uuid.UUID
    variant: str
    caption: str
    scheduled_at: datetime
    status: PostStatus
    remote_id: str | None
    attempts: int
    last_error: str | None
    published_at: datetime | None
    started_at: datetime | None = None
    remote_url: str | None = None
    metrics: dict


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    config: dict = {}


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    config: dict | None = None


class RuleOut(ORM):
    id: uuid.UUID
    name: str
    enabled: bool
    config: dict
    created_at: datetime


# ---------- jobs ----------


class JobEventOut(ORM):
    id: int
    at: datetime
    type: str
    message: str
    data: dict


class JobOut(ORM):
    id: uuid.UUID
    kind: str
    video_id: uuid.UUID | None
    payload: dict
    status: JobStatus
    attempts: int
    max_attempts: int
    progress: int
    run_after: datetime
    last_error: str | None
    error_kind: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class JobDetail(JobOut):
    result: dict
    events: list[JobEventOut] = []


# ---------- engines & system ----------


class EngineOut(BaseModel):
    id: str
    stage: Stage
    name: str
    kind: str
    description: str
    ok: bool
    message: str
    selected: bool
    estimate: str | None = None


class EngineSelect(BaseModel):
    engine_id: str


class Health(BaseModel):
    ok: bool
    database: bool
    storage_writable: bool
    storage_free_gb: float
    ffmpeg: bool
    ffprobe: bool
    workers_online: int
    queued_jobs: int
    failed_jobs: int
