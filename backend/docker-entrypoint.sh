#!/bin/sh
# clipstar api     -> run database migrations, then serve the API on :8000
# clipstar worker  -> run a job worker
# clipstar migrate -> only run migrations
set -e

wait_for_db() {
  python - <<'EOF'
import sys, time
from sqlalchemy import create_engine, text
from clipstar.config import get_settings
url = get_settings().database_url
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("select 1"))
        sys.exit(0)
    except Exception as e:
        print(f"waiting for database ({e.__class__.__name__})", flush=True)
        time.sleep(2)
print("database not reachable", flush=True)
sys.exit(1)
EOF
}

case "$1" in
  api)
    wait_for_db
    alembic upgrade head
    exec uvicorn clipstar.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers
    ;;
  worker)
    wait_for_db
    exec python -m clipstar.worker
    ;;
  migrate)
    wait_for_db
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
