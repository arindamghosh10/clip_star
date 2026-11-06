# clip_star architecture

## 1. Review of the plan: what was missing, what to add

The prototype covers the creator's daily screens. Building the real system exposed these gaps. Items marked **(added)** are now part of the plan; the phase that delivers each one is in `ROADMAP.md`.

### Missing for a self-hosted system to work at all
| Gap | Why it matters | Resolution |
|---|---|---|
| Setup wizard | Each self-hoster must register their own developer app with every platform (YouTube, Meta, TikTok, X, LinkedIn, Pinterest) and add storage, compute and engine keys. Without guidance nobody gets past install. | **(added)** First-run wizard + per-platform setup guide; health check per credential. |
| Login, users, roles | Teams and agencies need editor / approver / viewer roles and several workspaces. | **(added)** Users, workspaces, roles. Single-user mode by default. |
| Platform app credentials vs account tokens | Two different secrets: the app's client ID/secret (one per platform) and each account's OAuth token (one per account). | **(added)** Separate "Platform apps" settings; account tokens stored per account. |
| Jobs & activity screen | "Nothing crashes" is not achievable for any real system; what is achievable is that every failure is caught, retried, visible and fixable. | **(added)** Activity screen: every job, its attempts, error, logs, a Retry button. |
| Notifications | Approvals waiting, failed posts and expiring logins must reach the user outside the app. | **(added)** Email / webhook / push notifications. |

### Missing for quality results
| Gap | Resolution |
|---|---|
| Clip editor | **(added)** Trim start/end on the transcript, fix caption words, swap hook text, re-render. |
| Transcript correction | **(added)** Edit transcript words once; every clip from that video uses the fix. |
| Cover / thumbnail choice | **(added)** Pick a frame or upload a cover per clip. |
| Preflight checks per platform | **(added)** Before a post is scheduled, check length, aspect, size, caption length and hashtag count against that platform's current rules. A post that would fail is flagged at approval time, not at posting time. |
| AI content disclosure | **(added)** YouTube, TikTok and Meta ask creators to label realistic AI-altered content (e.g. a voice-cloned dub). Per-post "AI disclosure" flag, set automatically when dubbing is used. |
| Music / copyright check | **(added)** Warn when a clip contains recognisable copyrighted music before it is posted. |

### Missing for running it day to day
| Gap | Resolution |
|---|---|
| Spend caps per connector | **(added)** Monthly budget per paid connector; runs pause instead of overspending. |
| Storage lifecycle | **(added)** Keep masters N days, delete proxies after render, show disk usage. |
| Audit log | **(added)** Who approved which batch, who sent which reply. |
| Backups | **(added)** Database backup command and docs. |
| Time zones and daylight saving | **(added)** Schedules stored in UTC plus the account's IANA zone; posting hours computed per day so DST shifts are handled. |
| Integrations | **(added, later)** Public REST API, outgoing webhooks, and a clip_star MCP server so assistants can drive it. |

Nothing in the prototype needs to be removed.

## 2. Reliability design

The goal is that every failure is **contained, retried, visible and recoverable**, and that the system never does the dangerous thing twice (for example, posting the same clip twice).

### 2.1 Durable jobs
- Every unit of work (a pipeline stage for one video, one post, one metrics pull) is a row in `jobs` in Postgres.
- Workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED` and take a **lease** (default 10 min) that they renew while working.
- If a worker crashes or the machine restarts, the lease expires and another worker picks the job up. No work is lost.
- Failures retry with exponential backoff and jitter. After the last attempt the job becomes `failed`, appears on the Activity screen with its error, and can be retried by hand.
- Errors are classified: *retryable* (network, rate limit, timeout) vs *permanent* (bad input, revoked login). Permanent errors stop immediately and tell the user what to fix.
- Each job writes events (`started`, `progress`, `retry_scheduled`, `failed`, `succeeded`) to `job_events` for the UI and debugging.

### 2.2 Idempotent stages
- Each stage reads its inputs from storage and writes outputs under a deterministic path. Running a stage twice produces the same result and overwrites cleanly.
- A stage only marks the video as advanced after its outputs are written, inside one transaction.

### 2.3 Publishing safely (no double posts)
- Posts use an outbox pattern: `scheduled → publishing → published | failed | unknown`.
- Before calling a platform, the post records an attempt. If a call times out after the platform may have accepted it, the post becomes `unknown` and the publisher **checks the account's recent posts** before any retry, instead of re-posting blind.
- Per-account limits, spacing between accounts and quiet hours are enforced in the scheduler and re-checked just before posting.
- Disabling a batch is honoured right up to the moment of posting.

### 2.4 Agents that return correct output
- Every AI step returns JSON validated against a strict schema (Pydantic). Invalid output gets one repair attempt with the validation error; if it still fails, the step falls back to the deterministic engine (e.g. the rule-based moment finder) and records that it did.
- Outputs are checked against reality, not trusted: clip timestamps must lie inside the video, snap to word boundaries, and respect min/max length; captions must match the transcript; copy must fit each platform's limits.
- Calls have timeouts, retries and a per-run budget. Prompts, model, and responses are logged per job for debugging.
- The creator profile (voice, niche, banned topics) is passed to every agent; banned topics are also checked after generation.

### 2.5 Plugin contract
Each engine (free or paid) implements the same interface for its stage:

```python
class Engine(Protocol):
    id: str
    stage: Stage
    kind: Literal["free", "connector"]
    def check(self, settings) -> Health          # credentials, binaries, models present
    def estimate(self, ctx) -> CostEstimate      # shown before a run
    def run(self, ctx, inputs) -> StageOutput    # typed, validated output
```

Inputs and outputs are typed, so any engine can replace another without touching the pipeline.

### 2.6 Testing
- Unit tests for every stage and engine, run against a real Postgres.
- An end-to-end test generates a short sample video with FFmpeg and runs it through the free engines.
- Publishers are tested against recorded API responses; real posting is verified by the user with their own developer apps.

## 3. Components

```
apps/web         Next.js UI
services/api     FastAPI REST API (Python 3.12+)
services/worker  same codebase, runs the job loop (python -m clipstar.worker)
Postgres         all state, including the job queue
Storage          local disk by default; S3-compatible (MinIO, R2, S3) optional
```

One Python package (`clipstar`) holds models, pipeline, engines and publishers; the API and the worker are two entry points into it. No Redis or Temporal is required, which keeps self-hosting to one `docker compose up`.

## 4. Honest limits
- Posting to real platforms needs the self-hoster's own approved developer apps (TikTok audit, Meta app review, YouTube quota, a paid X API plan). The code follows the official APIs, but those approvals can only be obtained by the person running it.
- Without a GPU, transcription uses smaller Whisper models on CPU: slower, slightly less accurate. A GPU or a hosted transcription connector fixes both.
- "Viral" scoring starts as an informed estimate. It becomes reliable per creator only after the Measure stage has collected results.
