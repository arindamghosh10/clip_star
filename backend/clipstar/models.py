"""Database schema. All timestamps are timezone-aware UTC."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _enum(e: type[enum.Enum], name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint, so adding values later is a simple migration.
    return Enum(e, name=name, native_enum=False, create_constraint=True, length=32, values_callable=lambda x: [m.value for m in x], validate_strings=True)


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------- enums ----------


class Stage(str, enum.Enum):
    ingest = "ingest"
    understand = "understand"
    moments = "moments"
    edit = "edit"
    package = "package"
    publish = "publish"
    engage = "engage"
    measure = "measure"
    learn = "learn"


class VideoStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    ready = "ready"  # all implemented stages finished
    failed = "failed"
    cancelled = "cancelled"


class ClipStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Platform(str, enum.Enum):
    youtube = "youtube"
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"
    x = "x"
    linkedin = "linkedin"
    threads = "threads"
    pinterest = "pinterest"


class AccountStatus(str, enum.Enum):
    connected = "connected"
    reconnect = "reconnect"
    paused = "paused"
    disconnected = "disconnected"


class BatchStatus(str, enum.Enum):
    awaiting = "awaiting"
    running = "running"
    disabled = "disabled"
    finished = "finished"
    cancelled = "cancelled"


class PostStatus(str, enum.Enum):
    held = "held"  # waiting for batch approval, or batch disabled
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    unknown = "unknown"  # platform call timed out; must be verified before any retry
    cancelled = "cancelled"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# ---------- tables ----------


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(200))
    # creator profile, brand kit, safety defaults
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source_filename: Mapped[str] = mapped_column(String(300))
    status: Mapped[VideoStatus] = mapped_column(_enum(VideoStatus, "video_status"), default=VideoStatus.queued)
    stage: Mapped[Stage] = mapped_column(_enum(Stage, "stage"), default=Stage.ingest)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    assets: Mapped[list["Asset"]] = relationship(back_populates="video", cascade="all, delete-orphan", passive_deletes=True)
    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="ck_video_progress"),)


class Asset(Base):
    """A file produced for a video (master, proxy, audio, transcript, scenes, energy, renders…)."""

    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = _uuid()
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(500))  # relative to storage root
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()

    video: Mapped[Video] = relationship(back_populates="assets")
    __table_args__ = (UniqueConstraint("video_id", "kind", name="uq_asset_video_kind"),)


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[uuid.UUID] = _uuid()
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    score: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[ClipStatus] = mapped_column(_enum(ClipStatus, "clip_status"), default=ClipStatus.pending)
    copy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    variants: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    engine: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    __table_args__ = (
        CheckConstraint("end_s > start_s", name="ck_clip_range"),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_clip_score"),
    )


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"))
    handle: Mapped[str] = mapped_column(String(200))
    group_name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[AccountStatus] = mapped_column(_enum(AccountStatus, "account_status"), default=AccountStatus.connected)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    language: Mapped[str] = mapped_column(String(64), default="English")
    daily_cap: Mapped[int] = mapped_column(Integer, default=10)
    posting_start: Mapped[str] = mapped_column(String(5), default="09:00")  # local HH:MM
    posting_end: Mapped[str] = mapped_column(String(5), default="21:00")
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform", "handle", name="uq_account_handle"),
        CheckConstraint("daily_cap > 0", name="ck_account_cap"),
    )


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[BatchStatus] = mapped_column(_enum(BatchStatus, "batch_status"), default=BatchStatus.awaiting)
    variations: Mapped[str] = mapped_column(String(64), default="off")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    posts: Mapped[list["Post"]] = relationship(back_populates="batch", cascade="all, delete-orphan", passive_deletes=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[uuid.UUID] = _uuid()
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    variant: Mapped[str] = mapped_column(String(8), default="A")
    caption: Mapped[str] = mapped_column(Text, default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[PostStatus] = mapped_column(_enum(PostStatus, "post_status"), default=PostStatus.held)
    remote_id: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    batch: Mapped[Batch] = relationship(back_populates="posts")
    __table_args__ = (
        UniqueConstraint("batch_id", "account_id", "clip_id", name="uq_post_once_per_batch"),
        Index("ix_posts_status_time", "status", "scheduled_at"),
    )


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()


class EngineChoice(Base):
    __tablename__ = "engine_choices"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[Stage] = mapped_column(_enum(Stage, "stage"), primary_key=True)
    engine_id: Mapped[str] = mapped_column(String(64))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _uuid()
    kind: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus, "job_status"), default=JobStatus.queued)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower runs first
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(16))  # retryable | permanent
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["JobEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan", passive_deletes=True, order_by="JobEvent.id")
    __table_args__ = (
        Index("ix_jobs_claim", "status", "priority", "run_after"),
        # At most one active (queued or running) job per dedupe key.
        Index("uq_jobs_active_dedupe", "dedupe_key", unique=True, postgresql_where=text("status IN ('queued','running') AND dedupe_key IS NOT NULL")),
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = _created()
    type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    job: Mapped[Job] = relationship(back_populates="events")


class WorkerHeartbeat(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = _created()
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_job: Mapped[uuid.UUID | None] = mapped_column()
