"""Plan when each post goes out. Pure functions: no database, easy to test.

Rules, per account:
- only inside the account's posting hours, in its own time zone (daylight saving handled by zoneinfo)
- at most `daily_cap` posts per local day (counting posts already scheduled or published)
- at least `account_gap_min` minutes between two posts on the same account
And across accounts: the same clip goes out at least `spacing_min` minutes apart on different accounts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass
class AccountInfo:
    id: str
    platform: str
    handle: str
    timezone: str
    start: str  # "HH:MM" local
    end: str
    daily_cap: int
    status: str = "connected"


@dataclass
class ClipInfo:
    id: str
    title: str
    variants: list[str]  # rendered variant ids, e.g. ["A", "B"]
    preflight: dict = field(default_factory=dict)  # platform -> {"ok": bool, "problems": [...]}


@dataclass
class Slot:
    account_id: str
    clip_id: str
    variant: str
    at: datetime  # UTC


@dataclass
class Plan:
    slots: list[Slot]
    warnings: list[str]
    skipped: list[dict]  # {"clip_id", "account_id", "reason"}


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _window(d: date, a: AccountInfo, quiet_hours: bool) -> tuple[datetime, datetime]:
    tz = ZoneInfo(a.timezone)
    if not quiet_hours:
        start = datetime.combine(d, time(0, 0), tzinfo=tz)
        return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
    s, e = _hm(a.start), _hm(a.end)
    ws = datetime.combine(d, s, tzinfo=tz)
    we = datetime.combine(d, e, tzinfo=tz)
    if we <= ws:  # window crosses midnight, e.g. 18:00-02:00
        we += timedelta(days=1)
    return ws.astimezone(timezone.utc), we.astimezone(timezone.utc)


def next_slot(a: AccountInfo, earliest: datetime, taken: list[datetime], gap_min: int, quiet_hours: bool, horizon_days: int = 60) -> datetime | None:
    """Earliest time >= `earliest` that respects the account's window, daily cap and gap."""
    tz = ZoneInfo(a.timezone)
    gap = timedelta(minutes=gap_min)
    t = earliest
    for _ in range(horizon_days * 50):  # bounded loop; each pass moves t forward
        d = t.astimezone(tz).date()
        # a window that started the previous local day may still be open (crosses midnight)
        for day in (d - timedelta(days=1), d):
            ws, we = _window(day, a, quiet_hours)
            if ws <= t < we:
                break
        else:
            ws, we = _window(d, a, quiet_hours)
            if t < ws:
                t = ws
            else:
                ws, we = _window(d + timedelta(days=1), a, quiet_hours)
                t = ws
            if t > earliest + timedelta(days=horizon_days):
                return None
            continue
        # daily cap counts posts in the same window (the posting "day")
        if sum(1 for x in taken if ws <= x < we) >= a.daily_cap:
            t = _window(ws.astimezone(tz).date() + timedelta(days=1), a, quiet_hours)[0]
            continue
        clash = [x for x in taken if abs((x - t).total_seconds()) < gap.total_seconds()]
        if clash:
            t = max(clash) + gap
            continue
        return t
    return None


def plan(
    clips: list[ClipInfo],
    accounts: list[AccountInfo],
    start_at: datetime,
    existing: dict[str, list[datetime]] | None = None,
    *,
    spacing_min: int = 45,
    account_gap_min: int = 60,
    variations: str = "off",  # off | ab
    quiet_hours: bool = True,
    duplicate_warning: int = 5,
) -> Plan:
    if start_at.tzinfo is None:
        raise ValueError("start_at must be timezone-aware")
    start_at = start_at.astimezone(timezone.utc)
    taken: dict[str, list[datetime]] = defaultdict(list, {k: list(v) for k, v in (existing or {}).items()})
    warnings: list[str] = []
    skipped: list[dict] = []
    slots: list[Slot] = []

    usable = [a for a in accounts if a.status != "disconnected"]
    for a in accounts:
        if a.status == "disconnected":
            skipped.append({"clip_id": None, "account_id": a.id, "reason": f"{a.handle} is disconnected."})
        elif a.status in ("paused", "reconnect"):
            warnings.append(f"{a.handle} is {'paused' if a.status == 'paused' else 'waiting to be reconnected'}; its posts will wait until that's fixed.")
    usable.sort(key=lambda a: (a.platform, a.handle.lower()))

    if variations == "off" and len(usable) > duplicate_warning and clips:
        warnings.append(
            f"The same version of each clip goes to {len(usable)} accounts. Platforms can treat many identical posts as spam; "
            "consider A/B versions or different clips per account."
        )

    for c in clips:
        last_for_clip: datetime | None = None
        order = 0
        for a in usable:
            pf = c.preflight.get(a.platform)
            if pf is not None and not pf.get("ok", True):
                skipped.append({"clip_id": c.id, "account_id": a.id, "reason": f"{c.title}: doesn't fit {a.platform} ({'; '.join(pf.get('problems', []))})"})
                continue
            if not c.variants:
                skipped.append({"clip_id": c.id, "account_id": a.id, "reason": f"{c.title}: not rendered yet."})
                continue
            variant = c.variants[order % len(c.variants)] if variations == "ab" else c.variants[0]
            earliest = start_at if last_for_clip is None else max(start_at, last_for_clip + timedelta(minutes=spacing_min))
            at = next_slot(a, earliest, taken[a.id], account_gap_min, quiet_hours)
            if at is None:
                skipped.append({"clip_id": c.id, "account_id": a.id, "reason": f"No free slot for {a.handle} in the next 60 days (daily cap too low?)."})
                continue
            taken[a.id].append(at)
            slots.append(Slot(a.id, c.id, variant, at))
            last_for_clip = at
            order += 1
    slots.sort(key=lambda s: s.at)
    return Plan(slots, warnings, skipped)


def check_move(a: AccountInfo, at: datetime, taken: list[datetime], gap_min: int, quiet_hours: bool, same_clip_elsewhere: list[datetime], spacing_min: int) -> list[str]:
    """Why a hand-picked time breaks the posting rules (empty = fine). Used when someone drags a post in the calendar."""
    out: list[str] = []
    tz = ZoneInfo(a.timezone)
    local = at.astimezone(tz)
    win = None
    for day in (local.date() - timedelta(days=1), local.date()):
        ws, we = _window(day, a, quiet_hours)
        if ws <= at < we:
            win = (ws, we)
    if win is None:
        out.append(f"{local:%H:%M} is outside {a.handle}'s posting hours ({a.start}–{a.end}, {a.timezone}).")
        d = local.date()
        win = (datetime.combine(d, time(0, 0), tzinfo=tz).astimezone(timezone.utc), datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc))
    n = sum(1 for x in taken if win[0] <= x < win[1])
    if n >= a.daily_cap:
        out.append(f"{a.handle} already has {n} posts that day (limit {a.daily_cap}); the extra one would be moved to the next day when it's due.")
    close = [x for x in taken if abs((x - at).total_seconds()) < gap_min * 60]
    if close:
        out.append(f"Less than {gap_min} minutes from another post on {a.handle}.")
    if spacing_min and any(abs((x - at).total_seconds()) < spacing_min * 60 for x in same_clip_elsewhere):
        out.append(f"The same clip goes out on another account less than {spacing_min} minutes apart.")
    return out
