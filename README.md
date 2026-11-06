# clip_star

A self-hostable system for creators: one long video goes in, short clips come out, get published across many social accounts, earn comments and views, and the results teach the system what to clip next.

Every pipeline stage is a plugin slot. Run the free open-source engine, or connect a tool you already pay for (your account, your bill).

```
Ingest → Understand → Find moments → Edit → Package → Publish → Engage → Measure → Learn
                          ↑                                                      │
                          └──────────────── learning loop ───────────────────────┘
```

## Status

**Step 1: frontend prototype.** Every screen is clickable and runs on sample data in `apps/web/lib/data.ts`. Approving clips, approving or disabling batches, toggling rules and accounts, sending replies and switching engines all change what you see, but nothing is saved or sent anywhere yet.

## Run it

Requires Node 20+.

```bash
npm install
npm run dev        # http://localhost:3000
```

## Screens

| Route | Stage | What it shows |
|---|---|---|
| `/` | all | Pipeline, what needs you, scheduled and live posts, insights |
| `/videos`, `/videos/[id]` | 01–05 | Upload, pipeline progress, what the system understood, clips per video |
| `/clips` | 03–05 | Clips with score, reason, variants and per-platform copy; approve or reject |
| `/publishing` | 06 | Batches (approve once, disable any time), automation rules, variation matrix |
| `/calendar` | 06 | Week of posts across all accounts; switch single posts off |
| `/accounts` | — | Many accounts per platform, groups, status, daily caps, pause posting |
| `/engage` | 07 | Sorted comments on your own posts with drafted replies |
| `/analytics` | 08–09 | Views, top clips, weekly insights |
| `/engines` | all | Pick the engine for each stage, connections, run cost preview |
| `/settings` | — | Creator profile, brand kit, approvals, publishing safety defaults |

## Layout

```
apps/web/          Next.js + Tailwind frontend
  app/             one folder per screen
  components/      shell, shared UI, pipeline rail, clip card
  lib/data.ts      sample data (to be replaced by the API)
  lib/store.tsx    in-memory UI state for the prototype
```

## Next steps

1. API and database (accounts, videos, clips, batches, rules) behind the same screens.
2. Ingest + Understand workers (FFmpeg, WhisperX) and the plugin contract for engines.
3. Moment finder and renderer (local model or Claude, FFmpeg 9:16 + captions).
4. Publishers per platform through official APIs, batch scheduler with per-account limits.
5. Comment sync and reply drafts, analytics sync, weekly insights.
