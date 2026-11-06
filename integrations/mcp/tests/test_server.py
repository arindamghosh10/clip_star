"""MCP-level tests: tools are listed with safety hints, call the right API endpoints, and pass errors to the model."""

import asyncio
import json

import httpx
import pytest
from mcp import Client

from clipstar_mcp.api import ClipStar
from clipstar_mcp.server import build_server


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith("application/json") else None
        self.calls.append((req.method, req.url.path, dict(req.url.params), body, req.headers.get("authorization")))
        p = req.url.path
        if p == "/api/clips":
            return httpx.Response(200, json=[{"id": "c1", "video_id": "v1", "title": "Rent trap", "status": "pending", "score": 82, "start_s": 10, "end_s": 48.5, "hook": "3 RENT TRAPS", "reason": "Number hook", "variants": [{"id": "A"}, {"id": "B"}], "meta": {"renders": {"A": {}}, "preflight": {"x": {"ok": False, "problems": ["Caption is 300 characters; X allows 280."]}}}}])
        if p == "/api/clips/c1" and req.method == "PATCH":
            return httpx.Response(200, json={"id": "c1", "title": "Rent trap", "status": body.get("status", "approved"), "score": 82, "start_s": 0, "end_s": 30, "copy": {"x": {"caption": "New", "title": "", "hashtags": []}}, "meta": {}})
        if p == "/api/clips/missing":
            return httpx.Response(404, json={"detail": "Clip not found."})
        if p == "/api/batches/b1/approve":
            return httpx.Response(200, json={"id": "b1", "name": "B", "status": "running", "posts": 3, "posted": 0})
        if p == "/api/batches":
            return httpx.Response(201, json={"id": "b2", "name": body["name"], "status": "awaiting", "posts": 2, "accounts": 2, "clips": 1, "warnings": []})
        if p == "/api/events":
            return httpx.Response(200, json={"events": [{"id": 7, "type": "post.published", "data": {}}], "next_after": 7, "types": {}})
        if p == "/api/comments/k1/send":
            return httpx.Response(200, json={"id": "k1", "reply_status": "sending", "error": None})
        return httpx.Response(404, json={"detail": "Not found."})


@pytest.fixture
def setup():
    fake = FakeApi()
    api = ClipStar("http://cs", "cs_key", http=httpx.Client(base_url="http://cs", transport=httpx.MockTransport(fake)))
    return fake, build_server(api)


def run(server, name, args):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(name, args)

    return asyncio.run(go())


def data(r):
    if r.structured_content is not None:
        return r.structured_content.get("result", r.structured_content)
    return json.loads(r.content[0].text)


def test_tools_have_safety_hints(setup):
    _, server = setup

    async def go():
        async with Client(server) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    tools = asyncio.run(go())
    assert {"list_clips", "review_clips", "create_batch", "approve_batch", "send_reply", "recent_events", "add_video"} <= set(tools)
    assert tools["list_clips"].annotations.read_only_hint is True
    assert tools["approve_batch"].annotations.destructive_hint is True and tools["approve_batch"].annotations.open_world_hint is True
    assert tools["send_reply"].annotations.open_world_hint is True
    assert "PUBLISHES" in tools["approve_batch"].description


def test_list_clips_is_compact_and_flags_text_problems(setup):
    fake, server = setup
    r = run(server, "list_clips", {"status": "pending"})
    assert not r.is_error
    clip = r.structured_content["result"][0]
    assert clip == {"id": "c1", "video_id": "v1", "title": "Rent trap", "status": "pending", "score": 82, "seconds": 38.5, "hook": "3 RENT TRAPS", "reason": "Number hook", "versions": ["A", "B"], "rendered": ["A"], "text_problems": {"x": ["Caption is 300 characters; X allows 280."]}}
    assert fake.calls[0][:3] == ("GET", "/api/clips", {"status": "pending"}) and fake.calls[0][4] == "Bearer cs_key"


def test_review_and_text_edit(setup):
    fake, server = setup
    r = run(server, "review_clips", {"clip_ids": ["c1", "missing"], "decision": "approved"})
    res = r.structured_content["result"]
    assert res[0]["status"] == "approved" and res[1] == {"id": "missing", "error": "Clip not found."}
    run(server, "update_clip_text", {"clip_id": "c1", "platform": "x", "caption": "New"})
    assert fake.calls[-1][3] == {"copy": {"x": {"caption": "New"}}}  # only sent fields


def test_publishing_needs_explicit_confirmation(setup):
    fake, server = setup
    r = run(server, "approve_batch", {"batch_id": "b1"})
    assert r.is_error and "confirm=true" in r.content[0].text
    assert not any(c[1].endswith("/approve") for c in fake.calls)
    r = run(server, "approve_batch", {"batch_id": "b1", "confirm": True})
    assert not r.is_error and data(r)["status"] == "running"
    r = run(server, "send_reply", {"comment_id": "k1", "text": "Thanks!"})
    assert r.is_error and "save_reply_draft" in r.content[0].text
    assert not run(server, "send_reply", {"comment_id": "k1", "text": "Thanks!", "confirm": True}).is_error


def test_create_batch_and_errors_reach_the_model(setup):
    fake, server = setup
    r = run(server, "create_batch", {"name": "Week 1", "clip_ids": ["c1"], "groups": ["Finance EN"], "start_at": "2026-11-07T09:00:00+00:00"})
    assert data(r)["status"] == "awaiting"
    assert fake.calls[-1][3] == {"name": "Week 1", "clip_ids": ["c1"], "account_ids": [], "groups": ["Finance EN"], "start_at": "2026-11-07T09:00:00+00:00", "variations": "off"}
    r = run(server, "get_clip", {"clip_id": "missing"})
    assert r.is_error and "Clip not found." in r.content[0].text


def test_add_video_checks_the_file(setup, tmp_path):
    _, server = setup
    r = run(server, "add_video", {"file_path": str(tmp_path / "nope.mp4")})
    assert r.is_error and "No file at" in r.content[0].text


def test_unreachable_server_message():
    api = ClipStar("http://cs", "cs_key", http=httpx.Client(base_url="http://cs", transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")))))
    r = run(build_server(api), "list_videos", {})
    assert r.is_error and "Can't reach clip_star" in r.content[0].text
