# clip_star · project status

The one place that says **what we plan to build** and **what is built**. Update it at the end of every phase (see "How to update" at the bottom).

**Last updated:** 2026-11-06 (Phase 10) · **Current phase:** 10 done; all planned phases built, real-platform verification next · **Branch:** `main`

Legend: ✅ built and tested · 🟡 built, not yet verified for real (see notes) · ⬜ planned, not built

---

## 1. What clip_star is

A self-hostable system for creators. One long video goes in. clip_star finds the best moments, edits them into vertical clips, writes post text for each platform, publishes to many accounts on a schedule, handles comments, measures results, and learns what to clip next. Every stage is a plugin slot: a free open-source engine or a paid tool on the creator's own account.

```
Ingest → Understand → Find moments → Edit → Package → Publish → Engage → Measure → Learn
                          ↑                                                      │
                          └──────────────── learning loop ───────────────────────┘
```

Design and reliability rules: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Connecting real platforms: [`PLATFORM_SETUP.md`](PLATFORM_SETUP.md)

---

## 2. Phases at a glance

| # | Phase | Status | Done when |
|---|---|---|---|
| 0 | Clickable frontend prototype | ✅ | Every screen renders on sample data |
| 1 | Backend foundation (API, database, migrations, tests) | ✅ | Tests pass against Postgres; API serves the screens |
| 2 | Durable job engine + Activity screen | ✅ | Jobs survive crashes, retry with backoff, failures visible and retryable |
| 3 | Ingest + Understand | ✅ / 🟡 | Real video → transcript, scenes, loud moments (Whisper 🟡, see §4) |
| 4 | Find moments + Edit | ✅ / 🟡 | Rendered 9:16 clips with captions and reasons (AI engines 🟡) |
| 5 | Package + clip editor | ✅ / 🟡 | Per-platform post text, limit checks, trim/hook/copy editing (AI copy 🟡) |
| 6 | Accounts + Publish | ✅ / 🟡 | Scheduled posts across accounts, no double posts (real platforms 🟡) |
| 7 | Engage | ✅ / 🟡 | Comments synced and sorted; approved replies appear on the platform (real platforms 🟡) |
| 8 | Measure + Learn | ✅ / 🟡 | Real stats per post/account; weekly insights; per-creator scoring (real platform stats 🟡) |
| 9 | Setup wizard, users/roles, notifications, budgets, storage lifecycle, backups | ✅ / 🟡 | Fresh install to first published clip without reading code (email delivery and Docker backups 🟡) |
| 10 | Public API, webhooks, clip_star MCP server | ✅ | External tools and assistants can drive clip_star |

---

## 3. Feature by feature

### Platform and reliability
| Feature | Status | Notes |
|---|---|---|
| Postgres job queue: claims, leases, crash recovery, backoff, cancel, manual retry, dedupe | ✅ | `backend/clipstar/jobs/` |
| Retryable vs permanent errors with plain-language messages | ✅ | |
| Activity screen: health, every job, attempts, event log, retry/cancel | ✅ | |
| Encrypted secrets (app keys, account logins) | ✅ | Key: `CLIPSTAR_SECRET_KEY` or `<storage>/.secret_key`, back it up |
| Optional API token (scripts and automation, owner rights) | ✅ | `CLIPSTAR_API_TOKEN` |
| Docker Compose (db, api, worker, web, Caddy proxy) | 🟡 | Validated, but images couldn't be built in the dev sandbox; run `docker compose up --build` once |
| First-run setup wizard (owner, profile, engines, accounts, first video) | ✅ | Open only until the owner exists; asks for the API token if one is set |
| Team sign-in: hashed passwords, 30-day sessions, lockout after 5 wrong tries, invite links, sign out everywhere on password change or disable | ✅ | See `docs/OPERATIONS.md` |
| Roles: owner, editor, reviewer, viewer, checked on every API call | ✅ | Always at least one owner |
| Multiple workspaces | ⬜ | Single workspace today |
| Notifications: bell in the app, one hook for every status change, deduplicated | ✅ | Batch waiting, post problems, reconnect, video ready/failed, leads, report, budget, disk, backups |
| Email notifications (SMTP), per-person choice of what to email | ✅ / 🟡 | Tested with a fake mail server; set `CLIPSTAR_SMTP_*` to use |
| Webhooks (signed, retried, auto-off after 20 failures, internal addresses blocked) and an ordered event feed | ✅ | 11 event types; `docs/API.md` |
| Personal API keys (role-capped, revocable, rate-limited) and interactive API reference at `/api/docs` | ✅ | |
| MCP server for AI assistants (`integrations/mcp`): 21 tools, publishing/replying need explicit confirmation | ✅ | Tested in-process, over stdio against the live API, and by a contract test in the backend suite |
| Push notifications to phones | ⬜ | Not planned yet (webhooks to a push service work today) |
| Monthly budget for paid engines; over budget the free engine takes over | ✅ | Estimated from token counts and configurable prices |
| Storage: usage by kind, audio clean-up, rejected-render clean-up, optional archiving, purge of old records, low-disk alert | ✅ | Daily, owner sets the rules |
| Backups: database + encryption key (+ optional media), daily with rotation, download, restore command | ✅ / 🟡 | Round-trip tested with pg_dump/pg_restore 16; Docker image install of the client tools not built in the sandbox |

### 01 Ingest
| Feature | Status | Notes |
|---|---|---|
| Upload (MP4/MOV/MKV/WebM/M4V/AVI), streamed, size limit | ✅ | Large files stream through the Caddy proxy |
| Probe, 720p preview, 16 kHz audio, rotated phone videos | ✅ | |
| Optional .srt/.vtt captions with the upload | ✅ | Skips speech recognition |
| Import from Google Drive / Dropbox / links | ⬜ | Shown in prototype only |
| YouTube new-upload alerts | ⬜ | |

### 02 Understand
| Feature | Status | Notes |
|---|---|---|
| Transcript from captions file | ✅ | |
| Transcript with faster-whisper (local, word timings) | 🟡 | Model download was blocked in the sandbox; tested with a stand-in model |
| Scene cuts, audio energy and loud moments | ✅ | |
| Speaker detection (diarization) | ⬜ | |
| Hosted transcription connectors (Deepgram, AssemblyAI) | ⬜ | |

### 03 Find moments
| Feature | Status | Notes |
|---|---|---|
| Sentence-bounded clips, hook/energy/completeness/length scoring, reasons | ✅ | Intros, outros and sponsor reads pushed down |
| Banned topics, length limits, no overlaps, no-speech fallback | ✅ | |
| Claude engine (structured output, fallback on refusal) | 🟡 | Tested with fake answers; needs `CLIPSTAR_ANTHROPIC_API_KEY` |
| Ollama local-model engine | 🟡 | Tested with fake answers; needs an Ollama server |
| Validation, one repair attempt, fall back to rules with a visible note | ✅ | |
| OpenAI engine | ⬜ | |
| External clipping vendors (Klap, OpusClip, Reap, Submagic, Vizard, Lumiclip, ScaleReach) | ⬜ | Plugin slot exists; connectors not built |

### 04 Edit
| Feature | Status | Notes |
|---|---|---|
| 1080×1920 render, loudness to -14 LUFS, cover image | ✅ | |
| Speaker-following crop per scene / blurred full-frame fit / vertical sources | ✅ / 🟡 | Face crop tested with a simulated detector; try on a real talking-head video |
| Word-by-word captions (Bold) and boxed captions (Clean), hook title | ✅ | |
| A/B versions, resumable renders, output checks, re-render job | ✅ | |
| B-roll, zooms, emojis, music, dubbing (ElevenLabs) | ⬜ | |

### 05 Package
| Feature | Status | Notes |
|---|---|---|
| Title, caption, hashtags for 8 platforms (templates) | ✅ | |
| Claude / Ollama copy engines with fallback to templates | 🟡 | Tested with fake answers |
| Per-platform limit checks (preflight), banned topics, auto-approve | ✅ | Limits are conservative defaults in `pipeline/package.py`; platforms change them |
| AI-content disclosure flag, music/copyright check | ⬜ | |

### Clip review and editing
| Feature | Status | Notes |
|---|---|---|
| Clips screen with real players, A/B switch, approve/reject/restore, re-render | ✅ | |
| Clip editor: trim on sentences, hooks, caption style, per-platform text | ✅ | |
| Fix a word everywhere (transcript + all captions, re-render) | ✅ | |
| Custom cover upload, transcript editing screen | ⬜ | |

### 06 Accounts and Publish
| Feature | Status | Notes |
|---|---|---|
| Practice accounts (full flow, nothing posted, failure modes) | ✅ | |
| Platform app keys in Settings; connect through official login (OAuth, PKCE where supported) | ✅ / 🟡 | Flow tested with a fake platform |
| Token refresh, reconnect prompts | ✅ | |
| Publishers: YouTube, Instagram, Facebook, Threads, TikTok, X, LinkedIn, Pinterest | 🟡 | Request sequences tested against fake servers; **no real post made yet** |
| Scheduler: posting hours per time zone (DST-safe), daily caps, gaps, spacing, A/B rotation | ✅ | |
| Batches: preview, approve, disable/enable, cancel; late approval shifts the plan | ✅ | |
| Automation rules (one batch per video, still needs approval) | ✅ | |
| No double posts: attempt recorded first, verify on uncertain results, crash recovery | ✅ | |
| Posts and Calendar screens with retry / cancel / "I see it posted" | ✅ | |
| Account groups, per-account settings, Pinterest board, YouTube visibility | ✅ | |
| Duplicate-clip warning across many accounts | ✅ | |
| Drag-and-drop rescheduling in the calendar | ⬜ | |

### 07 Engage · 08 Measure · 09 Learn
| Feature | Status | Notes |
|---|---|---|
| Comment sync from own posts every 15 min (or on demand), no duplicates | ✅ / 🟡 | YouTube, Instagram, Facebook, Threads, X; tested with practice accounts and fake platform servers. TikTok, LinkedIn, Pinterest: no comment API for apps |
| Sorting: question, lead, praise, critical, spam, other (rules; Claude/Ollama) | ✅ / 🟡 | AI engines tested with fake answers |
| Reply drafts: templates for praise and leads; AI drafts answer only from the clip; no links, banned topics, length checked | ✅ / 🟡 | |
| Send replies with no double sends (attempt recorded, uncertain = ask), retries, reconnect prompts | ✅ | |
| Auto-reply (praise, business enquiries only), hourly limit per account, auto-hide spam | ✅ | Applies to new comments |
| Engage inbox: categories, edit category, edit/send/skip/hide, handled tab | ✅ | |
| Stats per post at 1 h / 24 h / 3 d / 7 d; daily follower counts | ✅ / 🟡 | YouTube (incl. watch % via YouTube Analytics), Instagram, Facebook, Threads, X, TikTok, Pinterest; tested with practice accounts and fake platform servers. LinkedIn: no stats for personal posts |
| Account performance on the account page; results column in Posts | ✅ | |
| Live Overview and Analytics screens (7/30/90 days, by platform, by account, top posts) | ✅ | Practice numbers are clearly labelled |
| Insights ("do more / do less") compared per account, only with ≥5 posts per side and ≥20% difference | ✅ | Length, hook style, caption style, posting time, platform, A/B version |
| Ideas from viewer questions; re-clip suggestions for older videos (one click) | ✅ | Re-clipping keeps approved and posted clips |
| Per-creator scoring: learns from results, used in Find moments only if it beats the built-in rules on held-out posts | ✅ | Needs 20+ posts from 8+ clips with stats; blended 50/50; intro/outro penalties always apply |
| Weekly report (automatic, or "Create report now") | ✅ | Shown on Analytics; email delivery comes with notifications (Phase 9) |
| Optional research connector for trend/topic ideas (e.g. [agent-reach](https://github.com/Panniantong/agent-reach)) | ⬜ idea | Only its public, no-login sources, opt-in, never on the creator's own logged-in accounts. Its YouTube data uses yt-dlp (against YouTube's terms) and logged-in channels reuse browser cookies, so it stays out of the core pipeline. Official sources (YouTube search API, own comments and stats) come first. |

### Screens
| Screen | Data |
|---|---|
| All screens (Overview, Videos, Clips, clip editor, Accounts, account page, Publishing, Calendar, Posts, Engage, Analytics, Engines, Settings, Activity) | Live |

---

## 4. Not yet verified for real (and how to verify)

| Item | Why not yet | How to verify |
|---|---|---|
| Posting to each platform | Needs your developer apps and real accounts | Follow `PLATFORM_SETUP.md` for one platform, connect one account, post one approved clip |
| Reading and replying to comments on each platform | Same | After a real post gets comments, press "Check for new comments" on Engage and send one reply |
| Post stats and followers on each platform | Same; some stats need extra permissions or app review (e.g. Meta insights) | A day after a real post, open Analytics and the account page; compare with the platform's own numbers |
| Whisper transcription | Model download blocked in the dev sandbox | Upload a video without captions; check the transcript on the video page |
| Claude / Ollama engines | No API key or Ollama server in the sandbox | Set the key or start Ollama, select the engine in Engines & connectors, process a video |
| Face-following crop | Test videos had no people | Process a talking-head video; check the clip framing |
| Docker images | Builds couldn't download packages in the sandbox | `docker compose up --build`, open http://localhost:3000 |
| Email notifications | No mail server in the sandbox | Set `CLIPSTAR_SMTP_*`, invite yourself a second user, check the invite email arrives |
| Backups inside Docker | Same as Docker images | `docker compose exec worker python -m clipstar.backup create`, then restore into a test copy |

---

## 5. Known limits and decisions

- Self-hosted: whoever runs clip_star registers one developer app per platform (TikTok audit, Meta app review, YouTube quota, paid X plan). Meta and TikTok need an https redirect address.
- TikTok posts are private until the app passes TikTok's audit. Threads needs this server reachable from the internet.
- Not built on purpose: proxies or IP rotation per account, fingerprint spoofing, automatic account creation, edits made only to dodge duplicate detection, commenting on other people's content.
- Uncertain posts are never re-sent automatically; the user decides after a check.
- A fresh install is open until the owner account is created in the setup wizard; finish setup right away (or set `CLIPSTAR_API_TOKEN`, which the wizard then asks for).
- Stats are compared per account (each post against that account's typical views) so big accounts don't drown out small ones. With little data, Analytics says so rather than guessing.
- Practice accounts produce made-up stats with built-in patterns (number hooks and 35–50 s clips do better) so insights and learning can be tried; they are always labelled.
- Rendering on CPU takes roughly the clip's length per version; one version per clip is a setting.

---

## 6. Open decisions

| Question | Options | Status |
|---|---|---|
| Open-source the whole platform or only the engines? | whole / engines only | Open |
| Who runs the free engines? | self-hosted / creator's own compute / hosted free tier | Self-hosted today |
| How clip_star earns money | hosted cloud / subscription / connector partnerships | Open |
| Order of platforms to verify for real | e.g. YouTube first (simplest approval) | Open |

---

## 7. Change log

| Date | Phase | What changed |
|---|---|---|
| 2026-11-04 | Plan | Product plan, gap review, plugin-based design, multi-account publishing design |
| 2026-11-05 | 0 | Clickable frontend prototype on sample data; posts log and per-account KPIs |
| 2026-11-06 | 1–3 | Backend, durable job engine, Ingest + Understand, Videos and Activity screens, Docker setup |
| 2026-11-06 | 4 | Find moments (rules, Claude, Ollama) and Edit (9:16, captions, A/B); live Clips screen |
| 2026-11-06 | 5 | Package (8 platforms, limit checks, auto-approve), clip editor, fix-a-word, live Settings and Engines |
| 2026-11-06 | 6 | Account connection, 8 publishers, scheduler, no-double-post worker, rules, live Accounts/Publishing/Calendar/Posts, setup guide |
| 2026-11-06 | — | PROJECT_STATUS.md added; agent-reach reviewed (noted as a possible optional research connector) |
| 2026-11-06 | 7 | Engage: comment sync (5 platforms + practice), sorting, drafts (rules/Claude/Ollama), safe replies with hourly limits, auto-reply and auto-hide, live Engage screen |
| 2026-11-06 | 8 | Measure + Learn: stats for 7 platforms + practice, follower counts, live Overview/Analytics/account performance, insights, ideas from questions, re-clip, learned scoring in Find moments, weekly reports |
| 2026-11-06 | 9 | Setup wizard, team sign-in and roles, notifications (bell + email), paid-engine budgets, storage clean-up and archiving, backups with restore; fixed Settings save failing once the learned model existed; `docs/OPERATIONS.md` |
| 2026-11-06 | 10 | Personal API keys, `/api/docs`, event feed, signed webhooks with retries and delivery log, MCP server package for AI assistants, Settings → Integrations; `docs/API.md` |

---

## How to update this file

At the end of each phase (or any change worth noting):
1. Change the status marks in §2 and §3 (⬜ → 🟡 → ✅). Use 🟡 whenever something hasn't been tried against the real service.
2. Move items out of §4 once verified for real, and note how.
3. Add a row to §7 with the date, phase and a one-line summary.
4. Update "Last updated" and "Current phase" at the top.
