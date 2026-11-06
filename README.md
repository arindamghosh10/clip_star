# clip_star

A self-hostable system for creators: one long video goes in, short clips come out, get published across many social accounts, earn comments and views, and the results teach the system what to clip next.

Every pipeline stage is a plugin slot. Run the free open-source engine, or connect a tool you already pay for (your account, your bill).

```
Ingest → Understand → Find moments → Edit → Package → Publish → Engage → Measure → Learn
                          ↑                                                      │
                          └──────────────── learning loop ───────────────────────┘
```

- Design and reliability rules: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Build phases and what's done: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Status

| Part | State |
|---|---|
| Durable job engine (retries, crash recovery, cancel, Activity screen) | **Working** |
| Ingest: upload, probe, 720p preview, audio | **Working** |
| Understand: transcript (Whisper or your .srt/.vtt), scene cuts, loud moments | **Working** |
| Find moments: rules engine (free), Claude (your API key), local model via Ollama | **Working** |
| Edit: 9:16 render, speaker-following crop or blurred fit, word-by-word captions, hook title, A/B variants, covers | **Working** |
| Package: title, caption and hashtags for 8 platforms (templates, Claude or Ollama), limit checks per platform, auto-approve | **Working** |
| Clip editor: trim on sentences, hooks, caption style, per-platform text, fix a word everywhere | **Working** |
| Accounts: connect through each platform's login (encrypted tokens, refresh, reconnect prompts) or practice accounts | **Working** |
| Publish: scheduler (posting hours per time zone, daily caps, spacing, A/B), batches with preview and approval, automation rules, publishers for YouTube, Instagram, Facebook, Threads, TikTok, X, LinkedIn, Pinterest, no double posts | **Working**; real posting needs your developer apps, see [`docs/PLATFORM_SETUP.md`](docs/PLATFORM_SETUP.md) |
| Videos, Clips, clip editor, Accounts, Publishing, Calendar, Posts, Engines, Settings and Activity screens | **Live** on the backend |
| Engage, Measure, Learn (Overview, Engage and Analytics screens) | Next phases; those screens show sample data |

## Run with Docker (one command)

```bash
docker compose up --build
```

Open http://localhost:3000. To let Claude pick moments, start with `ANTHROPIC_API_KEY=... docker compose up` and choose Claude under Engines & connectors (API: `PUT /api/engines/moments`). The first transcription downloads the Whisper model (about 500 MB for `small`). Change it with `CLIPSTAR_WHISPER_MODEL=base docker compose up`. Set `CLIPSTAR_API_TOKEN` to require a token on every API call.

## Run for development

Requirements: Python 3.11+, Node 20+, PostgreSQL 14+, FFmpeg.

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,whisper]"
export CLIPSTAR_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/clipstar
alembic upgrade head
uvicorn clipstar.api.main:app --port 8000      # API
python -m clipstar.worker                       # worker (separate terminal; run several if you like)

# frontend (another terminal, repo root)
npm install
npm run dev                                     # http://localhost:3000
```

Tests (need a Postgres database named `clipstar_test`):

```bash
cd backend && CLIPSTAR_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/clipstar_test pytest
```

## Layout

```
apps/web/            Next.js + Tailwind frontend
backend/clipstar/
  api/               REST API (FastAPI)
  jobs/              durable Postgres job queue and handler runtime
  pipeline/          pipeline stages (ingest, understand, …)
  engines/           plugin engines (whisper, captions file, …)
  worker.py          job worker process
backend/migrations/  database migrations (Alembic)
backend/tests/       tests against real Postgres and FFmpeg
deploy/Caddyfile     reverse proxy used by docker compose
```
