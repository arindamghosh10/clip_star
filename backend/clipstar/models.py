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
    # words (for captions), scoring features, layout, renders per variant, render errors
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
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
    # "oauth" = connected through the platform's login; "simulated" = practice account, posts are simulated
    connection: Mapped[str] = mapped_column(String(16), default="simulated", server_default="simulated")
    remote_id: Mapped[str | None] = mapped_column(String(200))  # the platform's id for this account/page/channel
    token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted JSON: access/refresh tokens, expiry, scopes
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    options: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))  # e.g. Pinterest board
    last_error: Mapped[str | None] = mapped_column(Text)
    comments_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last follower snapshot
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
    # "manual", or "rule:<rule id>:<video id>" so a rule creates at most one batch per video
    origin: Mapped[str] = mapped_column(String(120), default="manual", server_default="manual")
    warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    posts: Mapped[list["Post"]] = relationship(back_populates="batch", cascade="all, delete-orphan", passive_deletes=True)
    __table_args__ = (Index("uq_batch_rule_origin", "workspace_id", "origin", unique=True, postgresql_where=text("origin <> 'manual'")),)


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
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last time a platform call began
    remote_url: Mapped[str | None] = mapped_column(String(500))
    verify_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metrics_step: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # stats snapshots taken so far
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


class PlatformApp(Base):
    """The developer app a self-hoster registered with a platform (one per platform)."""

    __tablename__ = "platform_apps"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(300))
    secret_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = _updated()


class OAuthState(Base):
    """One pending "connect account" attempt; the state value proves the callback is ours."""

    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"))
    verifier: Mapped[str] = mapped_column(String(128))  # PKCE code verifier
    group_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = _created()


class CommentCategory(str, enum.Enum):
    question = "question"
    lead = "lead"
    praise = "praise"
    critical = "critical"
    spam = "spam"
    other = "other"


class ReplyStatus(str, enum.Enum):
    none = "none"  # nothing sent yet
    queued = "queued"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    unknown = "unknown"  # the platform may have posted the reply; never re-sent automatically


class Comment(Base):
    """A comment on one of our own posts."""

    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = _uuid()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), index=True)
    remote_id: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    commented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[CommentCategory] = mapped_column(_enum(CommentCategory, "comment_category"), default=CommentCategory.other)
    category_by: Mapped[str] = mapped_column(String(32), default="rules")  # rules | claude | ollama | user
    # open = waiting for the creator; done = replied/skipped/hidden
    state: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    draft: Mapped[str] = mapped_column(Text, default="")
    draft_by: Mapped[str] = mapped_column(String(32), default="")
    reply_text: Mapped[str] = mapped_column(Text, default="")
    reply_status: Mapped[ReplyStatus] = mapped_column(_enum(ReplyStatus, "reply_status"), default=ReplyStatus.none)
    reply_remote_id: Mapped[str | None] = mapped_column(String(200))
    reply_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reply_auto: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    __table_args__ = (
        UniqueConstraint("account_id", "remote_id", name="uq_comment_remote"),
        Index("ix_comments_state", "state", "category"),
    )


class PostMetric(Base):
    """A snapshot of one post's stats (taken 1 h, 1 day, 3 days and 7 days after publishing)."""

    __tablename__ = "post_metrics"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = _created()
    hours: Mapped[float] = mapped_column(Float)  # hours since publishing
    views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    watch_pct: Mapped[float | None] = mapped_column(Float)  # average % of the video watched
    avg_watch_s: Mapped[float | None] = mapped_column(Float)
    follows: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class AccountMetric(Base):
    __tablename__ = "account_metrics"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = _created()
    followers: Mapped[int | None] = mapped_column(BigInteger)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


# ---------- Phase 9: team, notifications, spending ----------


class Role(str, enum.Enum):
    owner = "owner"  # everything, including team, platform apps, budgets and backups
    editor = "editor"  # make clips, schedule and publish, change settings
    reviewer = "reviewer"  # approve clips, batches and replies
    viewer = "viewer"  # look only


class User(Base):
    """A person. What they can do in each workspace is in Membership; `workspace_id`/`role`/`prefs` here are
    their first workspace's values, kept for older code paths and migrations."""

    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=text("false"))  # runs this server: backups
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.viewer)
    password_hash: Mapped[str | None] = mapped_column(String(300))  # None until an invite is accepted
    invite_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notifications_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {"email": bool, "kinds": [..]} which notifications to email
    prefs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    """A person's place in a workspace: their role there, and their notification settings for it."""

    __tablename__ = "memberships"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.viewer)
    disabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    notifications_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prefs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="uq_membership"),)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"))  # the workspace this sign-in is looking at
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)  # sha256 of the cookie value
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warn | error
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_notifications_ws_created", "workspace_id", "created_at"),)


class EngineUsage(Base):
    """One call to a paid connector, with its estimated cost (for monthly budgets)."""

    __tablename__ = "engine_usage"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(60))
    stage: Mapped[str] = mapped_column(String(30))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_engine_usage_ws_created", "workspace_id", "created_at"),)


# ---------- Phase 10: public API, events, webhooks ----------


class ApiKey(Base):
    """A personal API key. It acts as its owner, never with more rights than the owner has."""

    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in the UI so keys can be told apart
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.viewer)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Event(Base):
    """Outbox of things that happened, in order. Feeds webhooks and the /api/events feed."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    fanned_out: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_events_pending", "id", postgresql_where=text("NOT fanned_out")),)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(String(200), default="")
    events: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))  # ["*"] = all
    secret_enc: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    disabled_reason: Mapped[str | None] = mapped_column(String(300))
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[uuid.UUID] = _uuid()
    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    response_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    """One browser or phone that gets push notifications for a person (Web Push)."""

    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class MusicTrack(Base):
    """A background music track the creator uploaded (and confirmed they may use)."""

    __tablename__ = "music_tracks"
    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(500))
    duration_s: Mapped[float] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    license_note: Mapped[str] = mapped_column(String(500), default="")  # where it's from / licence, in the creator's words
    created_at: Mapped[datetime] = _created()
