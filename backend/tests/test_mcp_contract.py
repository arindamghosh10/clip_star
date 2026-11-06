"""The MCP server's API client (integrations/mcp/clipstar_mcp/api.py) against the real API, with a real API key."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipstar.api.main import app
from clipstar.pipeline import register_all

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations" / "mcp"))
from clipstar_mcp.api import ClipStar, ClipStarError  # noqa: E402

from .test_publishing import make_clip  # noqa: E402

H = {"X-ClipStar": "1"}


@pytest.fixture
def cs(client):
    register_all()
    client.post("/api/auth/setup", json={"name": "Maya", "email": "maya@example.com", "password": "correct horse battery", "workspace_name": "W"}, headers=H)
    client.patch("/api/workspace", json={"settings": {"quiet_hours": False, "spacing_minutes": 0}}, headers=H)
    key = client.post("/api/keys", json={"name": "assistant", "role": "editor"}, headers=H).json()["key"]
    return ClipStar("http://testserver", key, http=TestClient(app))


def test_assistant_workflow_through_the_api(client, cs):
    acc = client.post("/api/accounts", json={"platform": "instagram", "handle": "@maya", "group_name": "Finance"}, headers=H).json()
    cid, vid = make_clip(client)
    assert [v["id"] for v in cs.videos()] == [vid]
    clip = cs.clip(cid)
    assert clip["post_text"]["instagram"]["caption"] == "Check your lease" and clip["rendered"] == ["A"]
    assert cs.set_clip_status(cid, "pending")["status"] == "pending"
    assert cs.set_clip_status(cid, "approved")["status"] == "approved"
    out = cs.update_clip_text(cid, "instagram", None, "Read this before you sign", None)
    assert out["post_text"]["instagram"]["caption"] == "Read this before you sign" and out["post_text"]["instagram"]["hashtags"] == ["rent"]
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    kw = dict(name="Week", clip_ids=[cid], account_ids=None, groups=["Finance"], start_at=start, variations="off", spacing_minutes=None)
    pv = cs.preview_batch(**kw)
    assert pv["posts"][0]["handle"] == "@maya"
    b = cs.create_batch(**kw)
    assert b["status"] == "awaiting" and b["posts"] == 1
    assert cs.batches("awaiting")[0]["id"] == b["id"]
    assert cs.batch_action(b["id"], "approve")["status"] == "running"
    assert cs.posts(status="scheduled")[0]["account_id"] == acc["id"]
    ev = cs.events()
    assert {"clip.approved", "batch.awaiting_approval", "batch.approved"} <= {e["type"] for e in ev["events"]}
    assert cs.events(after=ev["next_after"])["events"] == []
    assert cs.accounts()[0]["group"] == "Finance"
    assert cs.overview(7)["days"] == 7 and "insights" in cs.insights()
    assert cs.comments() == []


def test_errors_are_plain_language(cs, client):
    with pytest.raises(ClipStarError, match="Clip not found"):
        cs.clip("00000000-0000-0000-0000-000000000000")
    bad = ClipStar("http://testserver", "cs_wrong", http=TestClient(app))
    with pytest.raises(ClipStarError, match="CLIPSTAR_API_KEY"):
        bad.videos()
    with pytest.raises(ClipStarError, match="No file at"):
        cs.add_video("/nope/video.mp4")


def test_viewer_key_cannot_change_things(client, cs):
    key = client.post("/api/keys", json={"name": "read only", "role": "viewer"}, headers=H).json()["key"]
    ro = ClipStar("http://testserver", key, http=TestClient(app))
    cid, _ = make_clip(client)
    assert ro.clips()[0]["id"] == cid
    with pytest.raises(ClipStarError, match="Viewer"):
        ro.set_clip_status(cid, "approved")
