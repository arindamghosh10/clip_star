FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# ffmpeg for media; PostgreSQL 16 client tools (pg_dump/pg_restore) for backups, matching the db image
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY clipstar ./clipstar
ARG WITH_WHISPER=1
RUN if [ "$WITH_WHISPER" = "1" ]; then pip install ".[whisper]"; else pip install .; fi
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh /usr/local/bin/clipstar
RUN chmod +x /usr/local/bin/clipstar && useradd -m -u 1000 clipstar && mkdir -p /data && chown clipstar /data
USER clipstar

ENV CLIPSTAR_STORAGE_DIR=/data
ENTRYPOINT ["clipstar"]
CMD ["api"]
