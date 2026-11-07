# clip_star API, webhooks and MCP

Everything the app does can also be done from your own scripts, automation tools (n8n, Zapier, Make) and AI assistants.

- **Interactive reference:** `/api/docs` on your server, e.g. http://localhost:3000/api/docs. The machine-readable schema is at `/api/openapi.json`.
- **Auth:** a personal API key from **Settings → Integrations**.
- **Events:** poll `GET /api/events`, or register a webhook.
- **AI assistants:** the MCP server in `integrations/mcp`.

## API keys

Create a key in **Settings → Integrations → API keys**. The key is shown once. Send it as a bearer token:

```bash
curl -H "Authorization: Bearer cs_..." http://localhost:3000/api/clips?status=pending
```

- **Access:** a key acts as the person who made it, with the access chosen for the key (Viewer, Reviewer, Editor or Owner). It never gets more than that person has. If the person is demoted or disabled, the key follows straight away.
- **Limits on keys:** keys can't create other keys or change sign-in settings.
- **Rate limit:** each key gets 600 requests a minute (`CLIPSTAR_API_KEY_RATE_PER_MINUTE`). Above that the API answers `429` with `Retry-After`.
- **Revoking:** any time, in the same place. Owners can see and revoke everyone's keys.
- **Old shared token:** `CLIPSTAR_API_TOKEN` still works for server-level scripts, with owner rights.

Errors come back as JSON `{"detail": "…"}` in plain language. Show them to people as they are.

### Common calls

| What | Call |
|---|---|
| Upload a video | `POST /api/videos` (multipart: `file`, optional `title`, `captions`) |
| Add a video from a link | `POST /api/videos/import` `{"url": "https://drive.google.com/file/d/…"}` (Drive, Dropbox or a direct file link) |
| Music library | `GET /api/music`, `POST /api/music` (multipart `file`, `title`, `license_note`, `confirm_rights=true`), `DELETE /api/music/{id}` |
| Videos and their progress | `GET /api/videos`, `GET /api/videos/{id}` |
| Clips waiting for review | `GET /api/clips?status=pending` |
| Approve or reject a clip | `PATCH /api/clips/{id}` `{"status": "approved"}` |
| Change post text | `PATCH /api/clips/{id}` `{"copy": {"instagram": {"caption": "…"}}}` |
| Effects, music and AI label per version | `PATCH /api/clips/{id}` `{"variants": [{"id": "A", "caption_style": "bold-pop", "hook": "…", "zoom": true, "emoji": false, "music": {"track_id": "…", "volume": 0.18}}], "ai_content": true}` |
| Accounts | `GET /api/accounts` |
| Preview a schedule | `POST /api/batches/preview` |
| Schedule (waits for approval) | `POST /api/batches` `{"name", "clip_ids", "account_ids" or "groups", "start_at", "variations": "off"/"ab"}` |
| Approve, pause, resume or cancel a batch | `POST /api/batches/{id}/approve` (or `disable`, `enable`, `cancel`) |
| Posts and their stats | `GET /api/posts?status=published` |
| Move a waiting post | `POST /api/posts/{id}/reschedule` `{"scheduled_at": "…", "force": false}`. A rule break answers `409` with `detail.warnings`; send `force: true` to move anyway |
| Cover image | `POST /api/clips/{id}/cover/{version}` (multipart `file`), `POST …/cover/{version}/frame` `{"at_s": 2.5}`, `DELETE …/cover/{version}` |
| Correct the transcript | `PUT /api/videos/{id}/transcript/segments` `{"edits": [{"index": 3, "text": "…"}]}` |
| Workspaces | `GET /api/workspaces`. Keys work in their own workspace; the server token takes `X-ClipStar-Workspace: <id>` |
| Comments | `GET /api/comments?state=open&category=question` |
| Analytics | `GET /api/analytics/overview?days=7`, `GET /api/analytics/learn` |

## Events

Everything that happens is recorded in order. Fetch only what's new:

```bash
curl -H "Authorization: Bearer cs_..." "http://localhost:3000/api/events?after=0"
# → {"events": [{"id": 41, "type": "post.published", "created_at": "...", "data": {...}}], "next_after": 41}
curl -H "Authorization: Bearer cs_..." "http://localhost:3000/api/events?after=41&types=post.published,post.failed"
```

Events are kept for 30 days.

| Event | `data` includes |
|---|---|
| `video.ready` | `video_id`, `title`, `clips` |
| `video.failed` | `video_id`, `title`, `error`, `stage` |
| `clip.approved` / `clip.rejected` | `clip_id`, `video_id`, `title`, `score` |
| `batch.awaiting_approval` | `batch_id`, `name`, `origin` (set when an automation rule made it) |
| `batch.approved` | `batch_id`, `name` |
| `post.published` | `post_id`, `batch_id`, `clip_id`, `variant`, `account_id`, `platform`, `handle`, `remote_id`, `url` |
| `post.failed` | the same fields, plus `error` |
| `account.needs_reconnect` | `account_id`, `platform`, `handle`, `reason` |
| `comment.received` | `comment_id`, `account_id`, `platform`, `post_id`, `author`, `message`, `category` |
| `report.ready` | `report_id`, `summary` |

## Webhooks

Owners add webhooks in **Settings → Integrations → Webhooks**: an address, plus the events to receive (or everything). clip_star POSTs each event as JSON:

```json
{"id": 41, "type": "post.published", "created_at": "2026-11-07T09:00:03Z", "workspace_id": "…", "data": {"post_id": "…", "url": "https://…"}}
```

Each request has these headers:

| Header | Meaning |
|---|---|
| `X-ClipStar-Event` | The event type |
| `X-ClipStar-Delivery` | A unique delivery id. Retries keep the same id, so you can ignore duplicates. |
| `X-ClipStar-Signature` | `t=<unix time>,v1=<hex HMAC-SHA256>`, computed over `"<t>.<raw body>"` with the webhook's secret (shown once when you add the webhook) |

Check the signature before trusting a request:

```python
import hashlib, hmac, time

def valid(secret: str, body: bytes, header: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    t = int(parts["t"])
    if abs(time.time() - t) > 300:  # refuse old or replayed requests
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

```js
const crypto = require("crypto");
function valid(secret, rawBody, header) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > 300) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${parts.t}.${rawBody}`).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1));
}
```

**How delivery works:**

- **Success:** answer with a 2xx status within 10 seconds. Do slow work after you answer.
- **Retries:** timeouts, `408`, `429` and `5xx` are retried with growing gaps, about 6 tries in total. Other `4xx` answers are treated as a refusal and not retried.
- **Auto switch-off:** after 20 failed deliveries in a row, the webhook is switched off and owners are notified. Switch it back on in Settings. Each delivery attempt is listed there, and failed ones can be sent again.
- **Internal addresses are blocked:** localhost and private networks are refused, both when you add the webhook and when sending (after resolving the name). If your receiver runs on your own network (for example n8n next to clip_star), set `CLIPSTAR_WEBHOOK_ALLOW_PRIVATE=true`.
- **Secrets:** "New secret" replaces the old secret immediately.

## MCP server (AI assistants)

`integrations/mcp` is a small, separate package. It lets Claude or any other assistant that speaks MCP work with clip_star through the API above. An assistant can only do what its key allows, and clip_star records its actions like anyone else's.

**Set up:**

1. Create an API key. Use Editor for full use, or Viewer if the assistant should only look.
2. Install the package, in its own environment if you like:

   ```bash
   pip install ./integrations/mcp
   ```

3. Add it to your assistant.

   Claude Code:

   ```bash
   claude mcp add clipstar --env CLIPSTAR_URL=http://localhost:3000 --env CLIPSTAR_API_KEY=cs_... -- clipstar-mcp
   ```

   Claude Desktop and other clients (JSON config):

   ```json
   {
     "mcpServers": {
       "clipstar": {
         "command": "clipstar-mcp",
         "env": { "CLIPSTAR_URL": "http://localhost:3000", "CLIPSTAR_API_KEY": "cs_..." }
       }
     }
   }
   ```

4. To run it over HTTP instead of stdio: `clipstar-mcp --http --port 8765`. The endpoint is `/mcp`. It listens only on 127.0.0.1 unless you pass `--host`.

`CLIPSTAR_URL` is the address of the API. In Docker that's the web address (`http://localhost:3000`), because `/api` is passed through. In development it's `http://localhost:8000`.

**Tools:**

| Kind | Tools |
|---|---|
| Look | `get_overview`, `list_videos`, `get_video`, `list_clips`, `get_clip`, `list_accounts`, `list_batches`, `list_posts`, `get_insights`, `list_comments`, `recent_events`, `preview_batch` |
| Change things inside clip_star | `add_video` (a file on the machine running the MCP server), `review_clips`, `update_clip_text`, `create_batch` (it waits for approval), `pause_batch`, `save_reply_draft`, `reclip_video` |
| Public, need `confirm=true` | `approve_batch` (publishes), `send_reply` |

Each tool is marked read-only, editing or public, so assistants that respect these hints ask before acting. The public tools also refuse to run without `confirm=true`. The server tells the assistant to use them only when the user explicitly asks, and to otherwise leave approval to a person in the app.
