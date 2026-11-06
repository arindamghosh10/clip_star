from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from clipstar.publishing.scheduler import AccountInfo, ClipInfo, next_slot, plan

UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def acc(i, tz="America/New_York", start="09:00", end="21:00", cap=2, platform="instagram", status="connected"):
    return AccountInfo(id=f"a{i}", platform=platform, handle=f"@a{i}", timezone=tz, start=start, end=end, daily_cap=cap, status=status)


def clip(i, variants=("A", "B"), preflight=None):
    return ClipInfo(id=f"c{i}", title=f"Clip {i}", variants=list(variants), preflight=preflight or {})


def local(dt, tz=NY):
    return dt.astimezone(tz)


def test_posts_wait_for_the_local_window():
    start = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)  # 01:00 New York
    p = plan([clip(1)], [acc(1)], start)
    assert local(p.slots[0].at).hour == 9 and local(p.slots[0].at).minute == 0


def test_daily_cap_and_gap_per_account():
    start = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)  # 09:00 New York
    p = plan([clip(i) for i in range(5)], [acc(1, cap=2)], start, account_gap_min=60)
    days = [local(s.at).date() for s in p.slots]
    assert days.count(days[0]) == 2 and len(set(days)) == 3  # 2 + 2 + 1
    times = sorted(s.at for s in p.slots)
    assert all((b - a) >= timedelta(minutes=60) for a, b in zip(times, times[1:]))


def test_same_clip_is_spaced_across_accounts_and_ab_alternates():
    start = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
    accounts = [acc(i, cap=5) for i in range(4)]
    p = plan([clip(1)], accounts, start, spacing_min=45, variations="ab")
    times = sorted(s.at for s in p.slots)
    assert all((b - a) >= timedelta(minutes=45) for a, b in zip(times, times[1:]))
    assert sorted(s.variant for s in p.slots) == ["A", "A", "B", "B"]


def test_each_account_uses_its_own_time_zone():
    start = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
    p = plan([clip(1)], [acc(1, tz="Asia/Kolkata"), acc(2, tz="Europe/London")], start, spacing_min=0)
    by = {s.account_id: s.at for s in p.slots}
    assert by["a1"].astimezone(ZoneInfo("Asia/Kolkata")).hour == 9
    assert by["a2"].astimezone(ZoneInfo("Europe/London")).hour == 9


def test_daylight_saving_switch_keeps_local_hour():
    # US clocks go forward on 2026-03-08. 09:00 local should stay 09:00 local on both sides.
    a = acc(1, cap=1)
    p = plan([clip(i) for i in range(3)], [a], datetime(2026, 3, 7, 14, 0, tzinfo=UTC))
    hours = [local(s.at).hour for s in p.slots]
    dates = [local(s.at).date().isoformat() for s in p.slots]
    assert hours == [9, 9, 9] and dates == ["2026-03-07", "2026-03-08", "2026-03-09"]
    assert p.slots[0].at.hour == 14 and p.slots[1].at.hour == 13  # UTC offset changed


def test_window_crossing_midnight():
    a = acc(1, start="22:00", end="02:00", cap=3)
    t = next_slot(a, datetime(2026, 3, 3, 5, 30, tzinfo=UTC), [], 60, True)  # 00:30 local, inside window
    assert local(t).hour == 0 and local(t).minute == 30


def test_existing_posts_count_toward_cap():
    start = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
    existing = {"a1": [datetime(2026, 3, 2, 15, 0, tzinfo=UTC), datetime(2026, 3, 2, 17, 0, tzinfo=UTC)]}
    p = plan([clip(1)], [acc(1, cap=2)], start, existing)
    assert local(p.slots[0].at).date().day == 3


def test_skips_preflight_failures_unrendered_and_disconnected_and_warns():
    accounts = [acc(i, cap=9) for i in range(7)] + [acc(9, platform="x"), acc(10, status="disconnected"), acc(11, status="paused")]
    clips = [clip(1, preflight={"x": {"ok": False, "problems": ["too long"]}}), clip(2, variants=())]
    p = plan(clips, accounts, datetime(2026, 3, 2, 14, tzinfo=UTC))
    reasons = " ".join(s["reason"] for s in p.skipped)
    assert "doesn't fit x" in reasons and "not rendered" in reasons and "disconnected" in reasons
    assert any("spam" in w for w in p.warnings) and any("paused" in w for w in p.warnings)
    assert all(s.clip_id == "c1" for s in p.slots) and len(p.slots) == 8


def test_quiet_hours_off_allows_any_time_and_naive_start_rejected():
    p = plan([clip(1)], [acc(1)], datetime(2026, 3, 2, 6, 0, tzinfo=UTC), quiet_hours=False)
    assert p.slots[0].at == datetime(2026, 3, 2, 6, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        plan([clip(1)], [acc(1)], datetime(2026, 3, 2, 6, 0))
