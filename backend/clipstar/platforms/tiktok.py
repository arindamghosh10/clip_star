"""TikTok via the Content Posting API (Direct Post, file upload in chunks).

Until a TikTok app passes TikTok's audit, it can only post privately (SELF_ONLY) and to a few users.
The publisher picks the visibility from what TikTok says this account allows.
"""

from __future__ import annotations

from ..errors import PermanentError, RetryableError
from .base import Identity, Provider, PublishResult, Tokens, num
from .http import call, json_of
from .util import bearer, url, wait_until

API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024


def _check(d: dict, label: str) -> dict:
    err = d.get("error") or {}
    code = err.get("code", "ok")
    if code not in ("ok", "", None):
        msg = err.get("message") or code
        if code in ("rate_limit_exceeded", "spam_risk_too_many_posts"):
            raise RetryableError(msg, user_message=f"TikTok limit reached ({msg}); will retry later.")
        if code in ("access_token_invalid", "access_token_expired"):
            from .base import AuthExpired

            raise AuthExpired(msg, user_message="TikTok login expired. Reconnect the account.")
        raise PermanentError(msg, user_message=f"TikTok rejected the request: {msg}")
    return d.get("data") or {}


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, count) following TikTok's rules: one chunk up to 64 MB, else 10 MB chunks with the remainder in the last."""
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk


class TikTok(Provider):
    platform = "tiktok"
    label = "TikTok"
    scopes = ["user.info.basic", "user.info.stats", "video.publish", "video.list"]
    metrics_supported = True
    comments_note = "TikTok's posting API doesn't include comments."
    docs_url = "https://developers.tiktok.com/doc/content-posting-api-get-started"
    client_id_label = "Client key"

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url("https://www.tiktok.com/v2/auth/authorize/", client_key=app.client_id, scope=",".join(self.scopes), response_type="code", redirect_uri=redirect_uri, state=state)

    def _token(self, data: dict):
        d = json_of(call("POST", f"{API}/oauth/token/", label=self.label, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}), self.label)
        if "access_token" not in d:
            raise PermanentError(str(d), user_message=f"TikTok login failed: {d.get('error_description') or d.get('error') or d}")
        return Tokens.from_oauth(d, open_id=d.get("open_id"))

    def exchange(self, app, code, redirect_uri, verifier):
        return self._token({"client_key": app.client_id, "client_secret": app.client_secret, "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})

    def refresh(self, app, tokens):
        if not tokens.refresh_token:
            return None
        return self._token({"client_key": app.client_id, "client_secret": app.client_secret, "grant_type": "refresh_token", "refresh_token": tokens.refresh_token})

    def identities(self, app, tokens):
        d = _check(json_of(call("GET", url(f"{API}/user/info/", fields="open_id,display_name"), label=self.label, headers=bearer(tokens)), self.label), self.label)
        u = d.get("user", {})
        return [Identity(remote_id=u.get("open_id") or tokens.extra.get("open_id"), handle=u.get("display_name") or "TikTok account", tokens=tokens)]

    def publish(self, app, tokens, remote_id, req):
        h = {**bearer(tokens), "Content-Type": "application/json; charset=UTF-8"}
        info = _check(json_of(call("POST", f"{API}/post/publish/creator_info/query/", label=self.label, headers=h, json={}), self.label), self.label)
        max_d = info.get("max_video_post_duration_sec")
        if max_d and req.duration_s > max_d:
            raise PermanentError("too long", user_message=f"This TikTok account can post videos up to {max_d}s; the clip is {req.duration_s:.0f}s.")
        options = info.get("privacy_level_options") or ["SELF_ONLY"]
        wanted = req.account_options.get("privacy", "PUBLIC_TO_EVERYONE")
        privacy = wanted if wanted in options else ("PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else options[0])
        size = req.video.stat().st_size
        chunk, count = chunk_plan(size)
        init = _check(
            json_of(
                call(
                    "POST",
                    f"{API}/post/publish/video/init/",
                    label=self.label,
                    headers=h,
                    json={
                        "post_info": {"title": req.caption[:2200], "privacy_level": privacy, "disable_comment": False, "disable_duet": False, "disable_stitch": False, **({"is_aigc": True} if req.ai_generated else {})},
                        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count},
                    },
                ),
                self.label,
            ),
            self.label,
        )
        publish_id, upload_url = init["publish_id"], init["upload_url"]
        data = req.video.read_bytes()
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            # The last chunk completes the upload and TikTok starts posting: ambiguous on timeout.
            call("PUT", upload_url, label=self.label, commit=(i == count - 1), ok=(200, 201, 206), headers={"Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}"}, content=data[start : end + 1])

        def done():
            d = _check(json_of(call("POST", f"{API}/post/publish/status/fetch/", label=self.label, headers=h, json={"publish_id": publish_id}), self.label), self.label)
            st = d.get("status")
            if st == "PUBLISH_COMPLETE":
                ids = d.get("publicaly_available_post_id") or d.get("publicly_available_post_id") or []
                return str(ids[0]) if ids else publish_id
            if st == "FAILED":
                raise PermanentError(str(d), user_message=f"TikTok couldn't post the video: {d.get('fail_reason') or 'unknown reason'}")
            return None

        note = "Posted privately: TikTok only allows private posts until your app passes TikTok's audit." if privacy == "SELF_ONLY" else None
        try:
            post_id = wait_until(done, label=self.label, every=5, timeout=600)
        except PermanentError as e:
            if "took too long" in e.user_message:
                return PublishResult(publish_id, None, note or "Uploaded; TikTok is still processing it.")
            raise
        return PublishResult(post_id, None, note)

    def post_metrics(self, app, tokens, remote_id, post_remote_id, published_at, hints=None):
        d = _check(json_of(call("POST", url(f"{API}/video/query/", fields="id,view_count,like_count,comment_count,share_count"), label=self.label, headers={**bearer(tokens), "Content-Type": "application/json"}, json={"filters": {"video_ids": [str(post_remote_id)]}}), self.label), self.label)
        vids = d.get("videos") or []
        if not vids:
            return {}
        v = vids[0]
        return {"views": num(v.get("view_count")), "likes": num(v.get("like_count")), "comments": num(v.get("comment_count")), "shares": num(v.get("share_count"))}

    def account_followers(self, app, tokens, remote_id):
        d = _check(json_of(call("GET", url(f"{API}/user/info/", fields="follower_count"), label=self.label, headers=bearer(tokens)), self.label), self.label)
        return num(d.get("user", {}).get("follower_count"))
