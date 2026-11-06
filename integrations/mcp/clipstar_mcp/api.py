"""A small client for the clip_star HTTP API (plain httpx, no MCP imports, so it can be tested on its own).

Every method returns plain JSON-able data, trimmed to what an assistant needs to decide and act.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx


class ClipStarError(Exception):
    """The API refused or failed; the message is the server's plain-language explanation."""


def _clip(c: dict) -> dict:
    pf = (c.get("meta") or {}).get("preflight") or {}
    problems = {p: v.get("problems") for p, v in pf.items() if isinstance(v, dict) and not v.get("ok", True)}
    return {
        "id": c["id"], "video_id": c.get("video_id"), "title": c.get("title"), "status": c.get("status"), "score": c.get("score"),
        "seconds": round((c.get("end_s") or 0) - (c.get("start_s") or 0), 1), "hook": c.get("hook"), "reason": c.get("reason"),
        "versions": [v.get("id") for v in c.get("variants") or []], "rendered": sorted(((c.get("meta") or {}).get("renders") or {}).keys()),
        "text_problems": problems or None,
    }


class ClipStar:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, http: httpx.Client | None = None, timeout: float = 60.0):
        base_url = (base_url or os.environ.get("CLIPSTAR_URL") or "http://localhost:8000").rstrip("/")
        api_key = api_key or os.environ.get("CLIPSTAR_API_KEY")
        headers = {"Accept": "application/json", "User-Agent": "clipstar-mcp/1"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.base_url = base_url
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout)
        self.http.headers.update(headers)

    # ----- plumbing -----

    def _req(self, method: str, path: str, **kw) -> Any:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ClipStarError(f"Can't reach clip_star at {self.base_url}: {e}") from e
        if r.status_code == 204:
            return None
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg", d)) for d in detail)
            if r.status_code == 401:
                detail = detail or "Not signed in."
                detail += " Check CLIPSTAR_API_KEY (create one in clip_star → Settings → Integrations)."
            raise ClipStarError(detail or f"clip_star answered {r.status_code}.")
        return body

    def get(self, path: str, **params) -> Any:
        return self._req("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, json: Any = None) -> Any:
        return self._req("POST", path, json=json)

    def patch(self, path: str, json: Any) -> Any:
        return self._req("PATCH", path, json=json)

    # ----- reading -----

    def overview(self, days: int = 7) -> dict:
        o = self.get("/api/analytics/overview", days=days)
        return {k: o.get(k) for k in ("days", "totals", "previous", "by_platform", "top_posts", "scheduled", "practice_only")}

    def videos(self, status: str | None = None) -> list[dict]:
        vs = self.get("/api/videos")
        return [
            {"id": v["id"], "title": v["title"], "status": v["status"], "stage": v["stage"], "progress": v.get("progress"), "clips": v.get("clips"), "minutes": round((v.get("duration_s") or 0) / 60, 1), "error": v.get("error"), "created_at": v.get("created_at")}
            for v in vs
            if status is None or v["status"] == status
        ]

    def video(self, video_id: str) -> dict:
        v = self.get(f"/api/videos/{video_id}")
        return {k: v.get(k) for k in ("id", "title", "status", "stage", "progress", "error", "duration_s", "clips", "meta", "created_at")}

    def clips(self, status: str | None = None, video_id: str | None = None, limit: int = 50) -> list[dict]:
        return [_clip(c) for c in self.get("/api/clips", status=status, video_id=video_id)][:limit]

    def clip(self, clip_id: str) -> dict:
        c = self.get(f"/api/clips/{clip_id}")
        out = _clip(c)
        out["post_text"] = c.get("copy")
        out["transcript"] = " ".join(w.get("word", "") for w in (c.get("meta") or {}).get("words", []))[:4000]
        return out

    def accounts(self, platform: str | None = None) -> list[dict]:
        return [
            {"id": a["id"], "platform": a["platform"], "handle": a["handle"], "group": a.get("group_name"), "status": a["status"], "practice": a.get("connection") == "simulated", "timezone": a.get("timezone"), "daily_cap": a.get("daily_cap")}
            for a in self.get("/api/accounts", platform=platform)
        ]

    def batches(self, status: str | None = None) -> list[dict]:
        return [
            {k: b.get(k) for k in ("id", "name", "status", "posts", "posted", "accounts", "clips", "variations", "warnings", "created_at")}
            for b in self.get("/api/batches")
            if status is None or b["status"] == status
        ]

    def posts(self, status: str | None = None, account_id: str | None = None, batch_id: str | None = None, limit: int = 50) -> list[dict]:
        ps = self.get("/api/posts", status=status, account_id=account_id, batch_id=batch_id, limit=limit)
        return [
            {"id": p["id"], "batch_id": p["batch_id"], "account_id": p["account_id"], "clip_id": p["clip_id"], "version": p["variant"], "status": p["status"], "scheduled_at": p["scheduled_at"], "published_at": p.get("published_at"), "url": p.get("remote_url"), "error": p.get("last_error"), "stats": {k: v for k, v in (p.get("metrics") or {}).items() if not k.startswith("_")} or None}
            for p in ps
        ]

    def insights(self) -> dict:
        lv = self.get("/api/analytics/learn")
        m = lv.get("model") or {}
        return {"based_on_posts": lv.get("n"), "insights": lv.get("insights"), "ideas": lv.get("ideas"), "reclip_suggestions": lv.get("reclip"), "learned_scoring": {"on": bool(m.get("active")), "why": m.get("reason")} if m else None}

    def comments(self, state: str = "open", category: str | None = None, limit: int = 50) -> list[dict]:
        cs = self.get("/api/comments", state=state, category=category, limit=limit)
        return [
            {"id": c["id"], "platform": c.get("platform"), "account": c.get("handle"), "author": c.get("author"), "message": c.get("message"), "category": c.get("category"), "draft_reply": c.get("draft"), "reply_status": c.get("reply_status"), "clip": c.get("clip_title")}
            for c in cs
        ]

    def events(self, after: int = 0, types: str | None = None, limit: int = 50) -> dict:
        r = self.get("/api/events", after=after, types=types, limit=limit)
        return {"events": r["events"], "next_after": r["next_after"]}

    # ----- acting -----

    def add_video(self, file_path: str, title: str | None = None) -> dict:
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise ClipStarError(f"No file at {p}. Give a path on the machine where this MCP server runs.")
        with p.open("rb") as f:
            files = {"file": (p.name, f, mimetypes.guess_type(p.name)[0] or "video/mp4")}
            data = {"title": title} if title else {}
            try:
                r = self.http.post("/api/videos", files=files, data=data, timeout=None)
            except httpx.HTTPError as e:
                raise ClipStarError(f"Upload failed: {e}") from e
        if r.status_code >= 400:
            try:
                d = r.json().get("detail")
            except ValueError:
                d = None
            raise ClipStarError(str(d or f"Upload failed ({r.status_code})."))
        v = r.json()
        return {"id": v["id"], "title": v["title"], "status": v["status"]}

    def set_clip_status(self, clip_id: str, status: str) -> dict:
        return _clip(self.patch(f"/api/clips/{clip_id}", {"status": status}))

    def update_clip_text(self, clip_id: str, platform: str, title: str | None, caption: str | None, hashtags: list[str] | None) -> dict:
        cp = {k: v for k, v in {"title": title, "caption": caption, "hashtags": hashtags}.items() if v is not None}
        c = self.patch(f"/api/clips/{clip_id}", {"copy": {platform: cp}})
        out = _clip(c)
        out["post_text"] = {platform: (c.get("copy") or {}).get(platform)}
        return out

    def _batch_body(self, name: str, clip_ids: list[str], account_ids: list[str] | None, groups: list[str] | None, start_at: str, variations: str, spacing_minutes: int | None) -> dict:
        body = {"name": name, "clip_ids": clip_ids, "account_ids": account_ids or [], "groups": groups or [], "start_at": start_at, "variations": variations}
        if spacing_minutes is not None:
            body["spacing_minutes"] = spacing_minutes
        return body

    def preview_batch(self, **kw) -> dict:
        r = self.post("/api/batches/preview", self._batch_body(**kw))
        return {"posts": [{k: p[k] for k in ("handle", "platform", "clip", "variant", "at")} for p in r["posts"]], "warnings": r.get("warnings"), "skipped": r.get("skipped")}

    def create_batch(self, **kw) -> dict:
        b = self.post("/api/batches", self._batch_body(**kw))
        return {k: b.get(k) for k in ("id", "name", "status", "posts", "accounts", "clips", "warnings")}

    def batch_action(self, batch_id: str, action: str) -> dict:
        b = self.post(f"/api/batches/{batch_id}/{action}")
        return {k: b.get(k) for k in ("id", "name", "status", "posts", "posted")}

    def save_reply_draft(self, comment_id: str, text: str) -> dict:
        c = self.patch(f"/api/comments/{comment_id}", {"draft": text})
        return {"id": c["id"], "draft_reply": c.get("draft"), "reply_status": c.get("reply_status")}

    def send_reply(self, comment_id: str, text: str) -> dict:
        c = self.post(f"/api/comments/{comment_id}/send", {"text": text})
        return {"id": c["id"], "reply_status": c.get("reply_status"), "error": c.get("error")}

    def reclip(self, video_id: str) -> dict:
        return self.post(f"/api/videos/{video_id}/reclip")
