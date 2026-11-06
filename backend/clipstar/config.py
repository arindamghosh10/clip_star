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

    # faster-whisper (free transcription engine)
    whisper_model: str = "small"
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_compute_type: str = "auto"


@lru_cache
def get_settings() -> Settings:
    return Settings()
