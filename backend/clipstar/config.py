from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables prefixed CLIPSTAR_ (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="CLIPSTAR_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5433/clipstar"
    storage_dir: Path = Path("./data")

    # Optional shared secret. When set, every API call must send "Authorization: Bearer <token>".
    api_token: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]

    max_upload_bytes: int = 20 * 1024**3  # 20 GB
    allowed_video_extensions: tuple[str, ...] = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")
    allowed_caption_extensions: tuple[str, ...] = (".srt", ".vtt")

    # Job engine
    worker_lease_seconds: int = 600
    worker_poll_seconds: float = 1.0
    job_max_attempts: int = 5
    job_backoff_base_seconds: float = 5.0
    job_backoff_max_seconds: float = 900.0

    # Media
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    proxy_height: int = 720
    scene_threshold: float = 0.3

    # Find moments: AI engines
    anthropic_api_key: str | None = None  # falls back to ANTHROPIC_API_KEY
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"  # low | medium | high | xhigh | max
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Edit: rendering
    render_preset: str = "veryfast"  # x264 speed/quality trade-off
    render_crf: int = 21
    caption_font: str = "DejaVu Sans"

    # Publishing
    # Where the API is reachable from the browser (OAuth redirects come back here) and where the web app is.
    public_api_url: str = "http://localhost:8000"
    web_url: str = "http://localhost:3000"
    # Encryption key for app secrets and account tokens. If unset, one is created in <storage_dir>/.secret_key.
    secret_key: str | None = None
    # Public base address of this server, for platforms that download the video themselves (Threads).
    public_media_url: str | None = None
    meta_graph_version: str = "v23.0"
    linkedin_version: str = "202608"  # LinkedIn-Version header (YYYYMM); LinkedIn retires versions after ~1 year
    publish_check_seconds: float = 20.0

    # Team sign-in
    session_days: int = 30
    cookie_secure: bool = False  # set true when the web app is served over https
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # Email notifications (optional). Without SMTP, notifications only show in the app.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    # Estimated prices for paid engines (USD per million tokens), used for budgets. Check your provider's price list.
    claude_price_input_per_mtok: float = 4.0
    claude_price_output_per_mtok: float = 20.0

    # Webhooks: block private/internal addresses unless you run receivers on your own network (e.g. n8n next to clip_star).
    webhook_allow_private: bool = False
    webhook_timeout_seconds: float = 10.0
    webhook_disable_after_failures: int = 20
    # Personal API keys: requests per minute per key (per API process)
    api_key_rate_per_minute: int = 600

    # Backups: pg_dump/pg_restore must be installed. Scheduled backups run when backup_dir is set.
    backup_dir: Path | None = None
    backup_keep: int = 7
    pg_dump_bin: str = "pg_dump"
    pg_restore_bin: str = "pg_restore"
    platform_timeout_seconds: float = 120.0

    # faster-whisper (free transcription engine)
    whisper_model: str = "small"
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_compute_type: str = "auto"


@lru_cache
def get_settings() -> Settings:
    return Settings()
