"""YouTube Shorts via the YouTube Data API v3 (resumable upload). A vertical video under 3 minutes is a Short."""

from __future__ import annotations

from ..errors import PermanentError
from .base import App, Identity, Provider, PublishRequest, PublishResult, Tokens
from .http import call, json_of
from .util import bearer, text_matches, url

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTube(Provider):
    platform = "youtube"
    label = "YouTube"
    scopes = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
    docs_url = "https://developers.google.com/youtube/v3/guides/uploading_a_video"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url(AUTH, client_id=app.client_id, redirect_uri=redirect_uri, response_type="code", scope=" ".join(self.scopes), access_type="offline", prompt="consent", include_granted_scopes="true", state=state, code_challenge=code_challenge, code_challenge_method="S256")

    def exchange(self, app, code, redirect_uri, verifier):
        r = call("POST", TOKEN, label=self.label, data={"code": code, "client_id": app.client_id, "client_secret": app.client_secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier})
        return Tokens.from_oauth(json_of(r, self.label))

    def refresh(self, app, tokens):
        if not tokens.refresh_token:
            return None
        r = call("POST", TOKEN, label=self.label, data={"client_id": app.client_id, "client_secret": app.client_secret, "refresh_token": tokens.refresh_token, "grant_type": "refresh_token"})
        t = Tokens.from_oauth(json_of(r, self.label))
        t.refresh_token = t.refresh_token or tokens.refresh_token  # Google doesn't always send a new one
        return t

    def identities(self, app, tokens):
        r = call("GET", url(f"{API}/channels", part="snippet,contentDetails", mine="true"), label=self.label, headers=bearer(tokens))
        out = []
        for it in json_of(r, self.label).get("items", []):
            sn = it.get("snippet", {})
            uploads = it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            out.append(Identity(remote_id=it["id"], handle=sn.get("customUrl") or sn.get("title") or it["id"], tokens=tokens, options={"uploads_playlist": uploads}))
        if not out:
            raise PermanentError("no channel", user_message="This Google account has no YouTube channel.")
        return out

    def publish(self, app, tokens, remote_id, req: PublishRequest):
        title = (req.title or req.caption.split("\n")[0] or "Short")[:100]
        body = {
            "snippet": {"title": title, "description": req.caption[:5000], "tags": req.hashtags[:15], "categoryId": req.account_options.get("category_id", "22")},
            "status": {"privacyStatus": req.account_options.get("privacy", "public"), "selfDeclaredMadeForKids": False},
        }
        size = req.video.stat().st_size
        r = call(
            "POST",
            url(UPLOAD, uploadType="resumable", part="snippet,status"),
            label=self.label,
            headers={**bearer(tokens), "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
            json=body,
        )
        session = r.headers.get("location") or r.headers.get("Location")
        if not session:
            raise PermanentError("no upload session", user_message="YouTube didn't start the upload.")
        # Finishing the upload creates the video: a timeout here is ambiguous.
        r = call("PUT", session, label=self.label, commit=True, headers={**bearer(tokens), "Content-Type": "video/mp4"}, content=req.video.read_bytes())
        vid = json_of(r, self.label)["id"]
        return PublishResult(vid, f"https://www.youtube.com/shorts/{vid}")

    def find(self, app, tokens, remote_id, req, since):
        uploads = req.account_options.get("uploads_playlist")
        if not uploads:
            return None
        r = call("GET", url(f"{API}/playlistItems", part="snippet", playlistId=uploads, maxResults="10"), label=self.label, headers=bearer(tokens))
        title = (req.title or req.caption.split("\n")[0])[:100]
        for it in json_of(r, self.label).get("items", []):
            sn = it.get("snippet", {})
            if text_matches(sn.get("title"), title):
                vid = sn.get("resourceId", {}).get("videoId")
                if vid:
                    return PublishResult(vid, f"https://www.youtube.com/shorts/{vid}")
        return None
