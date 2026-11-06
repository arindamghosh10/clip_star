"""clip_star MCP server: lets an AI assistant work with clip_star through its public API.

Run:  CLIPSTAR_URL=http://localhost:3000 CLIPSTAR_API_KEY=cs_... clipstar-mcp            (stdio)
      clipstar-mcp --http --port 8765                                                   (Streamable HTTP)

The assistant can do only what the API key allows (the key's role), and everything it does is
checked and recorded by clip_star exactly as if a person did it in the app.
"""

from __future__ import annotations

import argparse
import functools
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .api import ClipStar, ClipStarError

INSTRUCTIONS = """clip_star turns long videos into short clips, posts them to many social accounts, and learns what works.

Typical flow: add_video -> wait until list_videos shows it ready -> list_clips(status="pending") ->
get_clip to read one -> review_clips to approve or reject -> preview_batch -> create_batch (waits for approval) ->
approve_batch only when the user has clearly said to publish.

Rules:
- Publishing and replying are public and can't be undone. Call approve_batch and send_reply only after the user
  explicitly asked for that specific action; set confirm=true then. Otherwise create batches and save reply drafts
  for a person to approve in the app.
- Practice accounts (practice=true) post nothing and their stats are made up; say so when reporting numbers.
- Times are ISO 8601 with a timezone, e.g. 2026-11-07T09:00:00+00:00.
- Use recent_events(after=<last id>) to see what changed since you last looked."""

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
EDIT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
PUBLIC = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)


def _explained(fn):
    """clip_star's own error messages are meant for people; pass them to the model instead of a generic failure."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ClipStarError as e:
            raise ToolError(str(e)) from e

    return wrapper


def build_server(api: ClipStar | None = None) -> MCPServer:
    cs = api or ClipStar()
    mcp = MCPServer("clip_star", instructions=INSTRUCTIONS, version="1.0.0")

    def mcp_tool(**kw):
        return lambda fn: mcp.tool(**kw)(_explained(fn))

    # ---------- look ----------

    @mcp_tool(annotations=RO)
    def get_overview(days: int = 7) -> dict:
        """Views, watch time, shares and follows for the last `days` days vs the period before, best posts, and how many posts are scheduled."""
        return cs.overview(days)

    @mcp_tool(annotations=RO)
    def list_videos(status: Literal["queued", "processing", "ready", "failed", "cancelled"] | None = None) -> list[dict]:
        """Long videos added to clip_star, newest first, with processing status and clip counts."""
        return cs.videos(status)

    @mcp_tool(annotations=RO)
    def get_video(video_id: str) -> dict:
        """One video's processing details, including notes from each stage (engine used, fallbacks, problems)."""
        return cs.video(video_id)

    @mcp_tool(annotations=RO)
    def list_clips(status: Literal["pending", "approved", "rejected"] | None = None, video_id: str | None = None, limit: int = 50) -> list[dict]:
        """Clips, best score first. pending = waiting for review. Includes why each moment was picked and any post-text problems."""
        return cs.clips(status, video_id, limit)

    @mcp_tool(annotations=RO)
    def get_clip(clip_id: str) -> dict:
        """One clip in full: transcript of what is said, hook, post text per platform, rendered versions."""
        return cs.clip(clip_id)

    @mcp_tool(annotations=RO)
    def list_accounts(platform: str | None = None) -> list[dict]:
        """Connected social accounts (id, platform, handle, group, status). Use ids or group names when scheduling."""
        return cs.accounts(platform)

    @mcp_tool(annotations=RO)
    def list_batches(status: Literal["awaiting", "running", "disabled", "finished", "cancelled"] | None = None) -> list[dict]:
        """Batches of scheduled posts. awaiting = needs approval before anything is posted."""
        return cs.batches(status)

    @mcp_tool(annotations=RO)
    def list_posts(status: Literal["held", "scheduled", "publishing", "published", "failed", "unknown", "cancelled"] | None = None, account_id: str | None = None, batch_id: str | None = None, limit: int = 50) -> list[dict]:
        """Individual posts with their schedule, link and latest stats."""
        return cs.posts(status, account_id, batch_id, limit)

    @mcp_tool(annotations=RO)
    def get_insights() -> dict:
        """What works for this creator (only patterns with enough data), ideas from viewer questions, older videos worth re-clipping, and whether learned scoring is on."""
        return cs.insights()

    @mcp_tool(annotations=RO)
    def list_comments(state: Literal["open", "done", "all"] = "open", category: Literal["question", "lead", "praise", "critical", "spam", "other"] | None = None, limit: int = 50) -> list[dict]:
        """Comments on the creator's own posts, sorted into categories, with any drafted reply."""
        return cs.comments(state, category, limit)

    @mcp_tool(annotations=RO)
    def recent_events(after: int = 0, types: str | None = None, limit: int = 50) -> dict:
        """What happened, in order (video.ready, clip.approved, post.published, post.failed, comment.received, ...). Pass the returned next_after next time to get only newer events. `types` is comma-separated."""
        return cs.events(after, types, limit)

    # ---------- change things inside clip_star ----------

    @mcp_tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
    def add_video(file_path: str, title: str | None = None) -> dict:
        """Upload a long video from a file on the machine running this MCP server. Processing starts automatically and takes a while; check list_videos."""
        return cs.add_video(file_path, title)

    @mcp_tool(annotations=EDIT)
    def review_clips(clip_ids: list[str], decision: Literal["approved", "rejected", "pending"]) -> list[dict]:
        """Approve or reject clips (or put them back to pending). Approving doesn't post anything; it makes the clip available for batches."""
        out = []
        for cid in clip_ids:
            try:
                out.append(cs.set_clip_status(cid, decision))
            except ClipStarError as e:
                out.append({"id": cid, "error": str(e)})
        return out

    @mcp_tool(annotations=EDIT)
    def update_clip_text(clip_id: str, platform: Literal["youtube", "instagram", "facebook", "tiktok", "x", "linkedin", "threads", "pinterest"], caption: str | None = None, title: str | None = None, hashtags: list[str] | None = None) -> dict:
        """Change the post text for one platform. Fields you leave out keep their value. The result shows any length or format problems."""
        return cs.update_clip_text(clip_id, platform, title, caption, hashtags)

    @mcp_tool(annotations=RO)
    def preview_batch(clip_ids: list[str], start_at: str, account_ids: list[str] | None = None, groups: list[str] | None = None, variations: Literal["off", "ab"] = "off", spacing_minutes: int | None = None, name: str = "Preview") -> dict:
        """Show exactly when each clip would post on each account (respecting posting hours, daily caps and spacing), plus warnings. Changes nothing."""
        return cs.preview_batch(name=name, clip_ids=clip_ids, account_ids=account_ids, groups=groups, start_at=start_at, variations=variations, spacing_minutes=spacing_minutes)

    @mcp_tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
    def create_batch(name: str, clip_ids: list[str], start_at: str, account_ids: list[str] | None = None, groups: list[str] | None = None, variations: Literal["off", "ab"] = "off", spacing_minutes: int | None = None) -> dict:
        """Schedule approved clips on accounts (by id and/or group). The batch waits for approval: nothing is posted until someone approves it."""
        return cs.create_batch(name=name, clip_ids=clip_ids, account_ids=account_ids, groups=groups, start_at=start_at, variations=variations, spacing_minutes=spacing_minutes)

    @mcp_tool(annotations=EDIT)
    def pause_batch(batch_id: str, action: Literal["disable", "enable", "cancel"]) -> dict:
        """Stop a batch (disable: pause; cancel: drop its unsent posts) or resume a paused one (enable)."""
        return cs.batch_action(batch_id, action)

    @mcp_tool(annotations=EDIT)
    def save_reply_draft(comment_id: str, text: str) -> dict:
        """Write or change the drafted reply to a comment, for a person to send from the app. Doesn't post anything."""
        return cs.save_reply_draft(comment_id, text)

    @mcp_tool(annotations=EDIT)
    def reclip_video(video_id: str) -> dict:
        """Find moments in a video again with the current settings and learned scoring. Approved and posted clips are kept."""
        return cs.reclip(video_id)

    # ---------- public actions (need explicit confirmation) ----------

    @mcp_tool(annotations=PUBLIC)
    def approve_batch(batch_id: str, confirm: bool = False) -> dict:
        """PUBLISHES: approve a batch so its posts go out publicly on schedule. Only when the user explicitly asked to publish this batch; pass confirm=true."""
        if not confirm:
            raise ClipStarError("Not approved: publishing is public. Ask the user to confirm, then call again with confirm=true.")
        return cs.batch_action(batch_id, "approve")

    @mcp_tool(annotations=PUBLIC)
    def send_reply(comment_id: str, text: str, confirm: bool = False) -> dict:
        """PUBLIC: post a reply to a comment on the platform. Only when the user explicitly asked to send it; pass confirm=true. Otherwise use save_reply_draft."""
        if not confirm:
            raise ClipStarError("Not sent: replies are public. Ask the user to confirm, then call again with confirm=true, or use save_reply_draft.")
        return cs.send_reply(comment_id, text)

    return mcp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="clipstar-mcp", description="MCP server for clip_star. Needs CLIPSTAR_URL and CLIPSTAR_API_KEY.")
    ap.add_argument("--http", action="store_true", help="serve over Streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise in an assistant's log
    server = build_server()
    if a.http:
        server.run(transport="streamable-http", host=a.host, port=a.port)
    else:
        server.run()


if __name__ == "__main__":
    main()
