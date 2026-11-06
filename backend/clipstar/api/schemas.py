"""Request/response shapes for the REST API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


class ClipPatch(BaseModel):
    status: ClipStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    hook: str | None = Field(default=None, max_length=200)
    copy_: dict[str, str] | None = Field(default=None, alias="copy")


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


class AccountPatch(BaseModel):
    group_name: str | None = Field(default=None, max_length=100)
    status: AccountStatus | None = None
    timezone: str | None = None
    language: str | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=500)
    posting_start: str | None = None
    posting_end: str | None = None

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
    created_at: datetime


# ---------- batches & posts ----------


class BatchOut(ORM):
    id: uuid.UUID
    name: str
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
