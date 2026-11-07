from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from clipstar.db import session_scope
from clipstar.models import Post
from clipstar.publishing.scheduler import AccountInfo, check_move

from .test_publishing import _setup, batch, make_account, make_clip, posts  # noqa: F401  (_setup is the autouse fixture)

UTC = timezone.utc


def acct(**kw):
    return AccountInfo("a", "instagram", "@maya", kw.get("tz", "UTC"), kw.get("start", "09:00"), kw.get("end", "21:00"), kw.get("cap", 2))


def test_check_move_rules():
    day = datetime(2026, 11, 10, tzinfo=UTC)
    assert check_move(acct(), day.replace(hour=12), [], 60, True, [], 45) == []
    w = check_move(acct(), day.replace(hour=23), [], 60, True, [], 45)
    assert len(w) == 1 and "outside" in w[0]
    assert check_move(acct(), day.replace(hour=23), [], 60, False, [], 45) == []  # quiet hours off
    w = check_move(acct(), day.replace(hour=12), [day.replace(hour=10), day.replace(hour=15)], 60, True, [], 45)
    assert any("limit 2" in x for x in w)
    w = check_move(acct(), day.replace(hour=12), [day.replace(hour=12, minute=30)], 60, True, [], 45)
    assert any("60 minutes" in x for x in w)
    w = check_move(acct(), day.replace(hour=12), [], 60, True, [day.replace(hour=12, minute=20)], 45)
    assert any("same clip" in x for x in w)
    # windows in the account's own time zone, including ones that cross midnight
    assert check_move(acct(tz="America/New_York"), day.replace(hour=15), [], 60, True, [], 45) == []  # 10:00 in New York
    assert check_move(acct(start="18:00", end="02:00"), day.replace(hour=1), [], 60, True, [], 45) == []


def future(hours):
    return (datetime.now(UTC) + timedelta(hours=hours)).replace(second=0, microsecond=0)


def test_reschedule_endpoint(client):
    cid, _ = make_clip(client)
    a = make_account(client)
    client.patch(f"/api/accounts/{a['id']}", json={"posting_start": "00:00", "posting_end": "23:59"})
    b = batch(client, cid, [a["id"]], approve=False)
    p = posts(client, b["id"])[0]
    to = future(30)
    r = client.post(f"/api/posts/{p['id']}/reschedule", json={"scheduled_at": to.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == [] and datetime.fromisoformat(r.json()["post"]["scheduled_at"]) == to
    assert client.post(f"/api/posts/{p['id']}/reschedule", json={"scheduled_at": datetime.now(UTC).isoformat()}).status_code == 422


def test_rule_break_needs_force(client):
    client.patch("/api/workspace", json={"settings": {"quiet_hours": True}})
    cid, _ = make_clip(client)
    a = make_account(client)
    client.patch(f"/api/accounts/{a['id']}", json={"posting_start": "09:00", "posting_end": "10:00", "timezone": "UTC"})
    b = batch(client, cid, [a["id"]], approve=False)
    p = posts(client, b["id"])[0]
    to = future(48).replace(hour=15)
    r = client.post(f"/api/posts/{p['id']}/reschedule", json={"scheduled_at": to.isoformat()})
    assert r.status_code == 409 and "outside" in r.json()["detail"]["warnings"][0]
    r = client.post(f"/api/posts/{p['id']}/reschedule", json={"scheduled_at": to.isoformat(), "force": True})
    assert r.status_code == 200 and r.json()["post"]["last_error"].startswith("Moved by hand")


def test_only_waiting_posts_move(client):
    cid, _ = make_clip(client)
    a = make_account(client)
    b = batch(client, cid, [a["id"]])
    p = posts(client, b["id"])[0]
    with session_scope() as s:
        s.execute(update(Post).where(Post.id == p["id"]).values(status="published"))
    assert client.post(f"/api/posts/{p['id']}/reschedule", json={"scheduled_at": future(5).isoformat()}).status_code == 409
    assert client.post("/api/posts/00000000-0000-0000-0000-000000000000/reschedule", json={"scheduled_at": future(5).isoformat()}).status_code == 404


def test_disclosure_warnings_in_preview(client):
    cid, _ = make_clip(client)
    a = make_account(client)  # instagram: no API field for AI labels
    y = make_account(client, handle="@yt", platform="youtube")
    assert client.patch(f"/api/clips/{cid}", json={"ai_content": True}).status_code == 200
    r = client.post("/api/batches/preview", json={"name": "B", "clip_ids": [cid], "account_ids": [a["id"], y["id"]], "start_at": future(1).isoformat()})
    w = r.json()["warnings"]
    assert any("AI-altered" in x and "instagram" in x and "youtube" not in x for x in w)
