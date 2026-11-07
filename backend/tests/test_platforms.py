"""Each platform's request sequence, run against a fake HTTP server.

These check that our side follows the official API flow as implemented (endpoints, order, headers,
chunking, polling, error mapping). They can't prove the live APIs still accept it: that needs real apps.
"""

import json

import httpx
import pytest

from clipstar.errors import PermanentError, RetryableError
from clipstar.platforms import util
from clipstar.platforms.base import Ambiguous, App, AuthExpired, PublishRequest, Tokens
from clipstar.platforms.http import call, set_transport
from clipstar.platforms.linkedin import LinkedIn, escape_little_text
from clipstar.platforms.meta import Facebook, Instagram, Threads
from clipstar.platforms.pinterest import Pinterest
from clipstar.platforms.tiktok import MB, TikTok, chunk_plan
from clipstar.platforms.x import X
from clipstar.platforms.youtube import YouTube

APP = App("cid", "secret")
TOK = Tokens("TOKEN")


class Fake:
    """Routes: list of (method, url_contains, handler(request) -> httpx.Response). First match wins; routes can repeat."""

    def __init__(self, routes):
        self.routes = routes
        self.log: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.log.append(req)
        for method, frag, fn in self.routes:
            if req.method == method and frag in str(req.url):
                return fn(req)
        return httpx.Response(404, json={"error": {"message": f"no route {req.method} {req.url}"}})

    def calls(self, frag):
        return [r for r in self.log if frag in str(r.url)]


def J(data, status=200, headers=None):
    return lambda req: httpx.Response(status, json=data, headers=headers or {})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(util, "sleep", lambda s: None)
    holder = {}

    def install(routes):
        f = Fake(routes)
        set_transport(httpx.MockTransport(f))
        holder["f"] = f
        return f

    yield install
    set_transport(None)


@pytest.fixture
def req(tmp_path):
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"v" * 3000)
    return PublishRequest(video=v, cover=None, title="Rent trap", caption="Nobody tells you this\n\n#rent", hashtags=["rent"], duration_s=30, post_id="p1")


def test_error_mapping(fake):
    fake([("GET", "/401", J({"error": "x"}, 401)), ("GET", "/429", J({}, 429)), ("GET", "/500", J({}, 500)), ("GET", "/400", J({"error": {"message": "bad caption"}}, 400))])
    with pytest.raises(AuthExpired):
        call("GET", "https://p.test/401", label="P")
    with pytest.raises(RetryableError):
        call("GET", "https://p.test/429", label="P")
    with pytest.raises(RetryableError):
        call("GET", "https://p.test/500", label="P")
    with pytest.raises(Ambiguous):
        call("GET", "https://p.test/500", label="P", commit=True)  # final call failing: may have posted
    with pytest.raises(PermanentError, match="bad caption"):
        try:
            call("GET", "https://p.test/400", label="P")
        except PermanentError as e:
            raise PermanentError(e.user_message)


def test_timeout_on_final_call_is_ambiguous(fake):
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    fake([("POST", "/x", boom)])
    with pytest.raises(Ambiguous):
        call("POST", "https://p.test/x", label="P", commit=True)
    with pytest.raises(RetryableError):
        call("POST", "https://p.test/x", label="P")


def test_youtube_resumable_upload(fake, req):
    f = fake(
        [
            ("POST", "uploadType=resumable", J({}, headers={"Location": "https://upload.test/session1"})),
            ("PUT", "upload.test/session1", J({"id": "vid123"})),
        ]
    )
    r = YouTube().publish(APP, TOK, "chan", req)
    assert r.remote_id == "vid123" and r.url.endswith("/shorts/vid123")
    meta = json.loads(f.calls("uploadType=resumable")[0].content)
    assert meta["snippet"]["title"] == "Rent trap" and meta["status"]["privacyStatus"] == "public" and meta["status"]["selfDeclaredMadeForKids"] is False
    put = f.calls("session1")[0]
    assert put.headers["authorization"] == "Bearer TOKEN" and len(put.content) == 3000


def test_youtube_auth_url_and_refresh_keeps_refresh_token(fake):
    u = YouTube().auth_url(APP, "st", "https://me/cb", "chal")
    assert "access_type=offline" in u and "code_challenge=chal" in u and "youtube.upload" in u
    fake([("POST", "oauth2.googleapis.com/token", J({"access_token": "new", "expires_in": 3600}))])
    t = YouTube().refresh(APP, Tokens("old", "R1", 0))
    assert t.access_token == "new" and t.refresh_token == "R1"


def test_instagram_reel_resumable_with_processing_poll(fake, req):
    states = iter(["IN_PROGRESS", "FINISHED"])
    f = fake(
        [
            ("POST", "/ig1/media_publish", J({"id": "media9"})),
            ("POST", "/ig1/media", J({"id": "cont1"})),
            ("POST", "rupload.facebook.com/ig-api-upload", J({"success": True})),
            ("GET", "/cont1", lambda r: httpx.Response(200, json={"status_code": next(states)})),
            ("GET", "/media9", J({"permalink": "https://instagram.com/reel/abc"})),
        ]
    )
    r = Instagram().publish(APP, TOK, "ig1", req)
    assert r.remote_id == "media9" and r.url == "https://instagram.com/reel/abc"
    up = f.calls("rupload")[0]
    assert up.headers["authorization"] == "OAuth TOKEN" and up.headers["file_size"] == "3000"
    assert b"media_type=REELS" in f.calls("/ig1/media")[0].content


def test_instagram_processing_error_is_permanent(fake, req):
    fake([("POST", "/ig1/media", J({"id": "c"})), ("POST", "rupload", J({})), ("GET", "/c", J({"status_code": "ERROR", "status": "Unsupported codec"}))])
    with pytest.raises(PermanentError, match="Unsupported codec"):
        Instagram().publish(APP, TOK, "ig1", req)


def test_facebook_reel_three_phases(fake, req):
    phases = []

    def reels(r):
        body = r.content.decode()
        phases.append("start" if "upload_phase=start" in body else "finish")
        return httpx.Response(200, json={"video_id": "v77", "upload_url": "https://rupload.facebook.com/video-upload/v23.0/v77"} if phases[-1] == "start" else {"success": True})

    fake([("POST", "/page1/video_reels", reels), ("POST", "rupload.facebook.com/video-upload", J({"success": True}))])
    r = Facebook().publish(APP, TOK, "page1", req)
    assert r.remote_id == "v77" and phases == ["start", "finish"]


def test_threads_needs_public_url_then_publishes(fake, req):
    with pytest.raises(PermanentError) as e:
        Threads().publish(APP, TOK, "u1", req)
    assert "public web address" in e.value.user_message
    req.account_options["_public_video_url"] = "https://clips.example.com/api/public/media/tok"
    f = fake([("POST", "/u1/threads_publish", J({"id": "t9"})), ("POST", "/u1/threads", J({"id": "c1"})), ("GET", "/c1", J({"status": "FINISHED"})), ("GET", "/t9", J({"permalink": "https://threads.net/t/9"}))])
    r = Threads().publish(APP, TOK, "u1", req)
    assert r.remote_id == "t9" and b"video_url=https" in f.calls("/u1/threads")[0].content


def test_tiktok_chunk_plan():
    assert chunk_plan(3 * MB) == (3 * MB, 1)
    assert chunk_plan(64 * MB) == (64 * MB, 1)
    size, n = chunk_plan(95 * MB)
    assert size == 10 * MB and n == 9  # last chunk carries the remaining 5 MB


def test_tiktok_direct_post_unaudited_goes_private(fake, req):
    f = fake(
        [
            ("POST", "creator_info/query", J({"data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 600}, "error": {"code": "ok"}})),
            ("POST", "video/init", J({"data": {"publish_id": "pub1", "upload_url": "https://upload.tiktok.test/u"}, "error": {"code": "ok"}})),
            ("PUT", "upload.tiktok.test", J({}, 201)),
            ("POST", "status/fetch", J({"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7001]}, "error": {"code": "ok"}})),
        ]
    )
    r = TikTok().publish(APP, TOK, "open1", req)
    assert r.remote_id == "7001" and "privately" in r.note
    init = json.loads(f.calls("video/init")[0].content)
    assert init["post_info"]["privacy_level"] == "SELF_ONLY" and init["source_info"]["video_size"] == 3000
    assert f.calls("upload.tiktok.test")[0].headers["content-range"] == "bytes 0-2999/3000"


def test_tiktok_api_error_in_200_body(fake, req):
    fake([("POST", "creator_info/query", J({"data": {}, "error": {"code": "spam_risk_too_many_posts", "message": "too many posts"}}))])
    with pytest.raises(RetryableError):
        TikTok().publish(APP, TOK, "open1", req)


def test_x_chunked_upload_then_post(fake, req, monkeypatch):
    import clipstar.platforms.x as xm

    monkeypatch.setattr(xm, "CHUNK", 1000)
    f = fake(
        [
            ("POST", "/media/upload/initialize", J({"data": {"id": "m1"}})),
            ("POST", "/media/upload/m1/append", J({}, 204)),
            ("POST", "/media/upload/m1/finalize", J({"data": {"id": "m1", "processing_info": {"state": "pending"}}})),
            ("GET", "command=STATUS", J({"data": {"processing_info": {"state": "succeeded"}}})),
            ("POST", "/2/tweets", J({"data": {"id": "tw9"}})),
        ]
    )
    req.account_options["username"] = "maya"
    r = X().publish(APP, TOK, "42", req)
    assert r.remote_id == "tw9" and r.url == "https://x.com/maya/status/tw9"
    assert len(f.calls("/append")) == 3
    body = json.loads(f.calls("/2/tweets")[0].content)
    assert body["media"]["media_ids"] == ["m1"] and len(body["text"]) <= 280


def test_linkedin_video_post(fake, req):
    f = fake(
        [
            ("POST", "action=initializeUpload", J({"value": {"video": "urn:li:video:V1", "uploadToken": "", "uploadInstructions": [{"uploadUrl": "https://up.test/1", "firstByte": 0, "lastByte": 2999}]}})),
            ("PUT", "up.test/1", J({}, 200, {"ETag": "etag-1"})),
            ("POST", "action=finalizeUpload", J({}, 200)),
            ("GET", "/rest/videos/urn", J({"status": "AVAILABLE"})),
            ("POST", "/rest/posts", lambda r: httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})),
        ]
    )
    r = LinkedIn().publish(APP, TOK, "abc", req)
    assert r.remote_id == "urn:li:share:9"
    fin = json.loads(f.calls("finalizeUpload")[0].content)
    assert fin["finalizeUploadRequest"]["uploadedPartIds"] == ["etag-1"]
    post = json.loads(f.calls("/rest/posts")[0].content)
    assert post["author"] == "urn:li:person:abc" and "\\#rent" in post["commentary"]
    assert f.calls("/rest/posts")[0].headers["linkedin-version"]
    assert escape_little_text("a (b) #c") == "a \\(b\\) \\#c"


def test_pinterest_needs_board_then_pins(fake, req):
    with pytest.raises(PermanentError, match="board"):
        Pinterest().publish(APP, TOK, "maya", req)
    req.account_options["board_id"] = "b1"
    f = fake(
        [
            ("POST", "/v5/media", J({"media_id": "md1", "upload_url": "https://s3.test/up", "upload_parameters": {"key": "k"}})),
            ("POST", "s3.test/up", J({}, 204)),
            ("GET", "/v5/media/md1", J({"status": "succeeded"})),
            ("POST", "/v5/pins", J({"id": "pin5"})),
        ]
    )
    r = Pinterest().publish(APP, TOK, "maya", req)
    assert r.remote_id == "pin5" and json.loads(f.calls("/v5/pins")[0].content)["board_id"] == "b1"


def test_meta_login_lists_pages_and_instagram_accounts(fake):
    fake(
        [
            ("GET", "oauth/access_token", J({"access_token": "long", "expires_in": 5000000})),
            ("GET", "/me/accounts", J({"data": [{"id": "p1", "name": "Maya Money", "access_token": "PT1", "instagram_business_account": {"id": "ig1", "username": "moneywithmaya"}}, {"id": "p2", "name": "Rent Facts", "access_token": "PT2"}]})),
        ]
    )
    t = Instagram().exchange(APP, "code", "https://me/cb", "v")
    ig = Instagram().identities(APP, t)
    fb = Facebook().identities(APP, t)
    assert [(i.remote_id, i.handle, i.tokens.access_token) for i in ig] == [("ig1", "@moneywithmaya", "PT1")]
    assert [i.handle for i in fb] == ["Maya Money", "Rent Facts"]


def test_ai_label_sent_only_where_supported(fake, req):
    import dataclasses

    ai = dataclasses.replace(req, ai_generated=True)
    f = fake([("POST", "uploadType=resumable", J({}, headers={"Location": "https://upload.test/s2"})), ("PUT", "upload.test/s2", J({"id": "v2"}))])
    YouTube().publish(APP, TOK, "chan", ai)
    assert json.loads(f.calls("uploadType=resumable")[0].content)["status"]["containsSyntheticMedia"] is True
    f = fake([("POST", "uploadType=resumable", J({}, headers={"Location": "https://upload.test/s3"})), ("PUT", "upload.test/s3", J({"id": "v3"}))])
    YouTube().publish(APP, TOK, "chan", req)
    assert "containsSyntheticMedia" not in json.loads(f.calls("uploadType=resumable")[0].content)["status"]
    f = fake(
        [
            ("POST", "creator_info/query", J({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"], "max_video_post_duration_sec": 600}, "error": {"code": "ok"}})),
            ("POST", "video/init", J({"data": {"publish_id": "pub2", "upload_url": "https://upload.tiktok.test/u2"}, "error": {"code": "ok"}})),
            ("PUT", "upload.tiktok.test", J({}, 201)),
            ("POST", "status/fetch", J({"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7002]}, "error": {"code": "ok"}})),
        ]
    )
    TikTok().publish(APP, TOK, "open1", ai)
    assert json.loads(f.calls("video/init")[0].content)["post_info"]["is_aigc"] is True
