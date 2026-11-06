"""Pinterest video Pins via API v5 (register media, upload, create pin on a board)."""

from __future__ import annotations

from ..errors import PermanentError
from .base import Identity, Provider, PublishResult, Tokens
from .http import call, json_of
from .util import bearer, text_matches, url, wait_until

API = "https://api.pinterest.com/v5"


class Pinterest(Provider):
    platform = "pinterest"
    label = "Pinterest"
    scopes = ["boards:read", "pins:read", "pins:write", "user_accounts:read"]
    docs_url = "https://developers.pinterest.com/docs/api-features/creating-boards-and-pins/"
    client_id_label = "App ID"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url("https://www.pinterest.com/oauth/", client_id=app.client_id, redirect_uri=redirect_uri, response_type="code", scope=",".join(self.scopes), state=state)

    def _token(self, app, data):
        r = call("POST", f"{API}/oauth/token", label=self.label, auth=(app.client_id, app.client_secret), data=data)
        return Tokens.from_oauth(json_of(r, self.label))

    def exchange(self, app, code, redirect_uri, verifier):
        return self._token(app, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    def refresh(self, app, tokens):
        if not tokens.refresh_token:
            return None
        t = self._token(app, {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token})
        t.refresh_token = t.refresh_token or tokens.refresh_token
        return t

    def identities(self, app, tokens):
        u = json_of(call("GET", f"{API}/user_account", label=self.label, headers=bearer(tokens)), self.label)
        boards = json_of(call("GET", url(f"{API}/boards", page_size="50"), label=self.label, headers=bearer(tokens)), self.label).get("items", [])
        opts = {"boards": [{"id": b["id"], "name": b.get("name", "")} for b in boards]}
        if boards:
            opts["board_id"] = boards[0]["id"]
        return [Identity(remote_id=u.get("username") or u.get("id", "pinterest"), handle=u.get("username") or "Pinterest account", tokens=tokens, options=opts)]

    def publish(self, app, tokens, remote_id, req):
        board = req.account_options.get("board_id")
        if not board:
            raise PermanentError("no board", user_message="Pick a Pinterest board for this account first (account settings).")
        h = bearer(tokens)
        m = json_of(call("POST", f"{API}/media", label=self.label, headers=h, json={"media_type": "video"}), self.label)
        media_id = m["media_id"]
        call("POST", m["upload_url"], label=self.label, ok=(200, 201, 204), data=m.get("upload_parameters", {}), files={"file": ("clip.mp4", req.video.read_bytes(), "video/mp4")})

        def ready():
            s = json_of(call("GET", f"{API}/media/{media_id}", label=self.label, headers=h), self.label).get("status")
            if s == "succeeded":
                return "ok"
            if s == "failed":
                raise PermanentError("media failed", user_message="Pinterest couldn't process the video.")
            return None

        wait_until(ready, label=self.label, every=5, timeout=600)
        p = json_of(
            call(
                "POST",
                f"{API}/pins",
                label=self.label,
                commit=True,
                headers=h,
                json={"board_id": board, "title": (req.title or req.caption)[:100], "description": req.caption[:500], "media_source": {"source_type": "video_id", "media_id": media_id, "cover_image_key_frame_time": 1}},
            ),
            self.label,
        )
        return PublishResult(p["id"], f"https://www.pinterest.com/pin/{p['id']}/")

    def find(self, app, tokens, remote_id, req, since):
        board = req.account_options.get("board_id")
        if not board:
            return None
        d = json_of(call("GET", url(f"{API}/boards/{board}/pins", page_size="10"), label=self.label, headers=bearer(tokens)), self.label)
        for p in d.get("items", []):
            if text_matches(p.get("title"), (req.title or req.caption)[:100]):
                return PublishResult(p["id"], f"https://www.pinterest.com/pin/{p['id']}/")
        return None
