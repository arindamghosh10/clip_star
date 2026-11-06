import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="clipstar-test-"))
os.environ.setdefault("CLIPSTAR_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/clipstar_test")
os.environ["CLIPSTAR_STORAGE_DIR"] = str(_TMP / "storage")
os.environ["CLIPSTAR_JOB_BACKOFF_BASE_SECONDS"] = "0.01"
os.environ["CLIPSTAR_JOB_BACKOFF_MAX_SECONDS"] = "0.05"
os.environ.pop("CLIPSTAR_API_TOKEN", None)
os.environ["CLIPSTAR_SECRET_KEY"] = "q4yJ1n1xF7n0VvDKl8wzG7Hn3c5a6TQm2u1gYvO0S2M="
os.environ["CLIPSTAR_PUBLIC_MEDIA_URL"] = "https://clips.example.com"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from clipstar.config import get_settings  # noqa: E402
from clipstar.db import get_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Build the test DB with the real migrations, so migrations are tested too."""
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    with get_engine().begin() as c:
        c.execute(text("TRUNCATE workspaces, videos, assets, clips, accounts, batches, posts, rules, engine_choices, jobs, job_events, workers, platform_apps, oauth_states CASCADE"))
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from clipstar.api.main import app

    with TestClient(app) as c:
        yield c


SAMPLE_SRT = """1
00:00:00,500 --> 00:00:03,000
Nobody tells you this about rent.

2
00:00:03,200 --> 00:00:06,000
I lost forty dollars a month for three years.

3
00:00:06,500 --> 00:00:10,500
Check your lease for the admin fee line!
"""


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """12 s, 640x360: 6 s test pattern then 6 s colour bars (one scene cut), tone with a loud burst at 8-9 s."""
    out = _TMP / "sample.mp4"
    if not out.exists():
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
                "-f", "lavfi", "-i", "smptebars=size=640x360:rate=25:duration=6",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=12:sample_rate=44100",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v];"
                "[2:a]volume='if(between(t,8,9),1.0,0.05)':eval=frame[a]",
                "-map", "[v]", "-map", "[a]", "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                str(out),
            ],
            check=True,
        )
    return out


@pytest.fixture
def sample_srt(tmp_path) -> Path:
    p = tmp_path / "sample.srt"
    p.write_text(SAMPLE_SRT)
    return p


def drain(worker, limit: int = 20) -> int:
    """Run jobs until the queue is empty (jobs scheduled for retry are run once their delay passes)."""
    import time

    ran = 0
    idle = 0
    while ran < limit and idle < 30:
        if worker.run_once():
            ran += 1
            idle = 0
        else:
            idle += 1
            time.sleep(0.02)
    return ran
