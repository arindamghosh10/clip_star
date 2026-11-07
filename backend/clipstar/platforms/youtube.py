"""YouTube Shorts via the YouTube Data API v3 (resumable upload). A vertical video under 3 minutes is a Short."""

from __future__ import annotations

from ..errors import PermanentError
from datetime import datetime, timezone

from .base import App, Identity, Provider, PublishRequest, PublishResult, RemoteComment, Tokens, num
from .http import call, json_of
from .util import bearer, text_matches, url

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTube(Provider):
    platform = "youtube"
    label = "YouTube"
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",  # read and reply to comments, moderate
        "https://www.googleapis.com/auth/yt-analytics.readonly",  # watch time, retention, shares
    ]
    metrics_supported = True
    comments_supported = True
    reply_max_chars = 10000
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
            "status": {"privacyStatus": req.account_options.get("privacy", "public"), "selfDeclaredMadeForKids": False, **({"containsSyntheticMedia": True} if req.ai_generated else {})},
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

    def list_comments(self, app, tokens, remote_id, post_remote_id):
        d = json_of(call("GET", url(f"{API}/commentThreads", part="snippet", videoId=post_remote_id, order="time", maxResults="50", textFormat="plainText"), label=self.label, headers=bearer(tokens)), self.label)
        out = []
        for t in d.get("items", []):
            top = t.get("snippet", {}).get("topLevelComment", {})
            sn = top.get("snippet", {})
            ch = (sn.get("authorChannelId") or {}).get("value")
            out.append(RemoteComment(top.get("id") or t["id"], sn.get("authorDisplayName", ""), sn.get("textDisplay") or sn.get("textOriginal", ""), _ts(sn.get("publishedAt")), is_own=ch == remote_id))
        return out

    def reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
        r = call("POST", url(f"{API}/comments", part="snippet"), label=self.label, commit=True, headers=bearer(tokens), json={"snippet": {"parentId": comment_remote_id, "textOriginal": text}})
        return json_of(r, self.label)["id"]

    def hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
        call("POST", url(f"{API}/comments/setModerationStatus", id=comment_remote_id, moderationStatus="heldForReview" if hidden else "published"), label=self.label, headers=bearer(tokens))

    def post_metrics(self, app, tokens, remote_id, post_remote_id, published_at, hints=None):
        d = json_of(call("GET", url(f"{API}/videos", part="statistics", id=post_remote_id), label=self.label, headers=bearer(tokens)), self.label)
        items = d.get("items", [])
        if not items:
            return {}
        st = items[0].get("statistics", {})
        out = {"views": num(st.get("viewCount")), "likes": num(st.get("likeCount")), "comments": num(st.get("commentCount"))}
        try:  # YouTube Analytics adds retention and shares; optional
            a = json_of(
                call(
                    "GET",
                    url("https://youtubeanalytics.googleapis.com/v2/reports", ids="channel==MINE", startDate=published_at.date().isoformat(), endDate=datetime.now(timezone.utc).date().isoformat(), metrics="averageViewPercentage,averageViewDuration,shares,subscribersGained", filters=f"video=={post_remote_id}"),
                    label=self.label,
                    headers=bearer(tokens),
                ),
                self.label,
            )
            cols = [h["name"] for h in a.get("columnHeaders", [])]
            row = (a.get("rows") or [[]])[0]
            vals = dict(zip(cols, row))
            out.update(watch_pct=vals.get("averageViewPercentage"), avg_watch_s=vals.get("averageViewDuration"), shares=num(vals.get("shares")), follows=num(vals.get("subscribersGained")))
        except Exception:
            pass
        return out

    def latest_uploads(self, app, tokens, remote_id, limit: int = 5) -> list[dict]:
        """The channel's newest uploads: [{id, title, published_at}] (newest first)."""
        ch = json_of(call("GET", url(f"{API}/channels", part="contentDetails", id=remote_id), label=self.label, headers=bearer(tokens)), self.label)
        items = ch.get("items") or []
        playlist = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") if items else None
        if not playlist:
            return []
        d = json_of(call("GET", url(f"{API}/playlistItems", part="snippet", playlistId=playlist, maxResults=str(limit)), label=self.label, headers=bearer(tokens)), self.label)
        out = []
        for it in d.get("items") or []:
            sn = it.get("snippet") or {}
            vid = (sn.get("resourceId") or {}).get("videoId")
            if vid:
                out.append({"id": vid, "title": sn.get("title", ""), "published_at": sn.get("publishedAt")})
        return out

    def account_followers(self, app, tokens, remote_id):
        d = json_of(call("GET", url(f"{API}/channels", part="statistics", id=remote_id), label=self.label, headers=bearer(tokens)), self.label)
        items = d.get("items", [])
        return num(items[0].get("statistics", {}).get("subscriberCount")) if items else None


def _ts(v):
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
