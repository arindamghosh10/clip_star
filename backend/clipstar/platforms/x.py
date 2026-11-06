"""X (Twitter) via API v2: OAuth 2.0 with PKCE, chunked media upload, then a post. Requires a paid X API plan."""

from __future__ import annotations

from ..errors import PermanentError
from datetime import datetime

from .base import Identity, Provider, PublishResult, RemoteComment, Tokens
from .http import call, json_of
from .util import bearer, text_matches, url, wait_until

API = "https://api.x.com/2"
CHUNK = 4 * 1024 * 1024


class X(Provider):
    platform = "x"
    label = "X"
    scopes = ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access", "tweet.moderate.write"]
    comments_supported = True
    comments_note = "Reading replies on X needs an API plan that includes search."
    reply_max_chars = 280
    docs_url = "https://docs.x.com/x-api/media/quickstart/media-upload-chunked"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url("https://x.com/i/oauth2/authorize", response_type="code", client_id=app.client_id, redirect_uri=redirect_uri, scope=" ".join(self.scopes), state=state, code_challenge=code_challenge, code_challenge_method="S256")

    def exchange(self, app, code, redirect_uri, verifier):
        r = call("POST", f"{API}/oauth2/token", label=self.label, auth=(app.client_id, app.client_secret), data={"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code_verifier": verifier, "client_id": app.client_id})
        return Tokens.from_oauth(json_of(r, self.label))

    def refresh(self, app, tokens):
        if not tokens.refresh_token:
            return None
        r = call("POST", f"{API}/oauth2/token", label=self.label, auth=(app.client_id, app.client_secret), data={"refresh_token": tokens.refresh_token, "grant_type": "refresh_token", "client_id": app.client_id})
        return Tokens.from_oauth(json_of(r, self.label))

    def identities(self, app, tokens):
        d = json_of(call("GET", f"{API}/users/me", label=self.label, headers=bearer(tokens)), self.label).get("data", {})
        return [Identity(remote_id=d["id"], handle=f"@{d.get('username', d['id'])}", tokens=tokens, options={"username": d.get("username")})]

    def publish(self, app, tokens, remote_id, req):
        h = bearer(tokens)
        size = req.video.stat().st_size
        d = json_of(call("POST", f"{API}/media/upload/initialize", label=self.label, headers=h, json={"media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"}), self.label)
        media_id = d.get("data", {}).get("id")
        if not media_id:
            raise PermanentError(str(d), user_message="X didn't start the media upload.")
        data = req.video.read_bytes()
        for i, start in enumerate(range(0, size, CHUNK)):
            call("POST", f"{API}/media/upload/{media_id}/append", label=self.label, headers=h, data={"segment_index": str(i)}, files={"media": ("clip.mp4", data[start : start + CHUNK], "application/octet-stream")})
        fin = json_of(call("POST", f"{API}/media/upload/{media_id}/finalize", label=self.label, headers=h), self.label).get("data", {})

        if fin.get("processing_info"):

            def ready():
                s = json_of(call("GET", url(f"{API}/media/upload", command="STATUS", media_id=media_id), label=self.label, headers=h), self.label).get("data", {})
                p = s.get("processing_info", {})
                if p.get("state") == "succeeded" or not p:
                    return "ok"
                if p.get("state") == "failed":
                    raise PermanentError(str(p), user_message=f"X couldn't process the video: {p.get('error', {}).get('message', 'unknown error')}")
                return None

            wait_until(ready, label=self.label, every=3, timeout=600)
        d = json_of(call("POST", f"{API}/tweets", label=self.label, commit=True, headers=h, json={"text": req.caption[:280], "media": {"media_ids": [media_id]}}), self.label)
        tid = d["data"]["id"]
        user = req.account_options.get("username")
        return PublishResult(tid, f"https://x.com/{user}/status/{tid}" if user else None)

    def find(self, app, tokens, remote_id, req, since):
        d = json_of(call("GET", url(f"{API}/users/{remote_id}/tweets", max_results="10", **{"tweet.fields": "created_at"}), label=self.label, headers=bearer(tokens)), self.label)
        for t in d.get("data", []) or []:
            if text_matches(t.get("text"), req.caption, 40):
                return PublishResult(t["id"], None)
        return None

    def list_comments(self, app, tokens, remote_id, post_remote_id):
        d = json_of(
            call(
                "GET",
                url(f"{API}/tweets/search/recent", query=f"conversation_id:{post_remote_id}", max_results="50", **{"tweet.fields": "author_id,created_at", "expansions": "author_id", "user.fields": "username"}),
                label=self.label,
                headers=bearer(tokens),
            ),
            self.label,
        )
        users = {u["id"]: u.get("username", "") for u in (d.get("includes") or {}).get("users", [])}
        out = []
        for t in d.get("data", []) or []:
            ts = t.get("created_at")
            when = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            out.append(RemoteComment(t["id"], "@" + users.get(t.get("author_id"), "user"), t.get("text", ""), when, is_own=t.get("author_id") == remote_id))
        return out

    def reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
        d = json_of(call("POST", f"{API}/tweets", label=self.label, commit=True, headers=bearer(tokens), json={"text": text[:280], "reply": {"in_reply_to_tweet_id": comment_remote_id}}), self.label)
        return d["data"]["id"]

    def hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
        call("PUT", f"{API}/tweets/{comment_remote_id}/hidden", label=self.label, headers=bearer(tokens), json={"hidden": hidden})
