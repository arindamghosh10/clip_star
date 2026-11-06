# clip_star build roadmap

Each phase ends with working, tested code. "Done when" is the check.

| Phase | Scope | Done when |
|---|---|---|
| 0 ✅ | Clickable frontend prototype | Every screen renders on sample data |
| 1 ✅ | Backend foundation: FastAPI, Postgres, schema, migrations, REST API, tests | `pytest` passes against Postgres; API serves the frontend's data |
| 2 ✅ | Durable job engine + plugin contract + Activity screen | Jobs survive worker crashes, retry with backoff, failures visible and retryable |
| 3 ✅ | Ingest + Understand (FFmpeg, faster-whisper, scenes, audio energy) | Uploading a real video produces a word-level transcript, scenes and energy map |
| 4 ✅ | Find moments + Edit (rules + LLM engines, 9:16 reframe, ASS captions, variants) | A video yields rendered vertical clips with captions and reasons |
| 5 | Package + approvals + clip editor | Per-platform copy, approve/reject, trim and re-render |
| 6 | Accounts + Publish (OAuth, token vault, scheduler, batches, rules, preflight, publishers for all 8 platforms) | Approved batch posts to connected accounts within limits, no double posts |
| 7 | Engage (comment sync, sorting, drafts, send) | Replies sent from the app appear on the platform |
| 8 | Measure + Learn (metrics sync, insights, per-creator scoring, re-clip) | Weekly report generated from real metrics |
| 9 | Setup wizard, users/roles, notifications, budgets, storage lifecycle, backups | Fresh install to first published clip without reading code |
| 10 | Public API, webhooks, clip_star MCP server | External tools can drive clip_star |
