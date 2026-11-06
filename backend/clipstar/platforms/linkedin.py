"""LinkedIn member posts with video (Videos API + Posts API). Uses the 'Share on LinkedIn' product."""

from __future__ import annotations

import re
from urllib.parse import quote

from ..config import get_settings
from ..errors import PermanentError
from .base import Identity, Provider, PublishResult, Tokens
from .http import call, json_of
from .util import bearer, url, wait_until

REST = "https://api.linkedin.com/rest"


def escape_little_text(s: str) -> str:
    """LinkedIn's commentary format reserves these characters; escape them so text shows as written."""
    return re.sub(r"([\\|{}@\[\]()<>#*_~])", r"\\\1", s)


class LinkedIn(Provider):
    platform = "linkedin"
    label = "LinkedIn"
    scopes = ["openid", "profile", "w_member_social"]
    comments_note = "LinkedIn only gives comment access to approved Community Management partners."
    metrics_note = "LinkedIn only shares post stats with approved partners."
    docs_url = "https://learn.microsoft.com/linkedin/marketing/community-management/shares/videos-api"

    def _h(self, tokens):
        return {**bearer(tokens), "LinkedIn-Version": get_settings().linkedin_version, "X-Restli-Protocol-Version": "2.0.0"}

    def auth_url(self, app, state, redirect_uri, code_challenge):
        return url("https://www.linkedin.com/oauth/v2/authorization", response_type="code", client_id=app.client_id, redirect_uri=redirect_uri, state=state, scope=" ".join(self.scopes))

    def exchange(self, app, code, redirect_uri, verifier):
        r = call("POST", "https://www.linkedin.com/oauth/v2/accessToken", label=self.label, data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": app.client_id, "client_secret": app.client_secret})
        return Tokens.from_oauth(json_of(r, self.label))

    def refresh(self, app, tokens):
        if not tokens.refresh_token:
            return None  # most apps get no refresh token: reconnect every ~60 days
        r = call("POST", "https://www.linkedin.com/oauth/v2/accessToken", label=self.label, data={"grant_type": "refresh_token", "refresh_token": tokens.refresh_token, "client_id": app.client_id, "client_secret": app.client_secret})
        return Tokens.from_oauth(json_of(r, self.label))

    def identities(self, app, tokens):
        d = json_of(call("GET", "https://api.linkedin.com/v2/userinfo", label=self.label, headers=bearer(tokens)), self.label)
        return [Identity(remote_id=d["sub"], handle=d.get("name") or d["sub"], tokens=tokens)]

    def publish(self, app, tokens, remote_id, req):
        owner = f"urn:li:person:{remote_id}"
        h = self._h(tokens)
        size = req.video.stat().st_size
        v = json_of(call("POST", f"{REST}/videos?action=initializeUpload", label=self.label, headers=h, json={"initializeUploadRequest": {"owner": owner, "fileSizeBytes": size, "uploadCaptions": False, "uploadThumbnail": False}}), self.label).get("value", {})
        video_urn, token = v.get("video"), v.get("uploadToken", "")
        if not video_urn:
            raise PermanentError(str(v), user_message="LinkedIn didn't start the video upload.")
        data = req.video.read_bytes()
        etags = []
        for ins in v.get("uploadInstructions", []):
            a, b = int(ins["firstByte"]), int(ins["lastByte"])
            r = call("PUT", ins["uploadUrl"], label=self.label, headers={"Content-Type": "application/octet-stream"}, content=data[a : b + 1])
            etags.append(r.headers.get("etag") or r.headers.get("ETag"))
        call("POST", f"{REST}/videos?action=finalizeUpload", label=self.label, headers=h, json={"finalizeUploadRequest": {"video": video_urn, "uploadToken": token, "uploadedPartIds": etags}})

        def ready():
            s = json_of(call("GET", f"{REST}/videos/{quote(video_urn, safe='')}", label=self.label, headers=h), self.label)
            st = s.get("status")
            if st == "AVAILABLE":
                return "ok"
            if st == "PROCESSING_FAILED":
                raise PermanentError(str(s), user_message="LinkedIn couldn't process the video.")
            return None

        wait_until(ready, label=self.label, every=5, timeout=600)
        r = call(
            "POST",
            f"{REST}/posts",
            label=self.label,
            commit=True,
            headers=h,
            json={
                "author": owner,
                "commentary": escape_little_text(req.caption[:3000]),
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "content": {"media": {"title": (req.title or req.caption)[:200], "id": video_urn}},
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
        )
        pid = r.headers.get("x-restli-id") or json_of(r, self.label).get("id", "")
        return PublishResult(pid, f"https://www.linkedin.com/feed/update/{pid}" if pid else None)
