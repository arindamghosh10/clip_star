"""Spending on paid connectors (BYOK): every call is metered with an estimated cost, and a monthly
budget can stop paid engines. When the budget is used up, paid engines decline and the free engine
takes over with a visible note, so work never stops because of money.
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from .config import get_settings
from .models import EngineUsage, Video, Workspace


@dataclass
class Scope:
    stage: str = ""
    video_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None


_scope: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("clipstar_budget_scope", default=None)


@contextmanager
def scope(stage: str, video_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None):
    tok = _scope.set(Scope(stage, video_id, workspace_id))
    try:
        yield
    finally:
        _scope.reset(tok)


def month_start(at: datetime | None = None) -> datetime:
    at = at or datetime.now(timezone.utc)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _workspace_id(s, sc: Scope | None) -> uuid.UUID | None:
    if sc and sc.workspace_id:
        return sc.workspace_id
    if sc and sc.video_id:
        v = s.get(Video, sc.video_id)
        if v:
            return v.workspace_id
    return s.scalar(select(Workspace.id).order_by(Workspace.created_at).limit(1))  # single-workspace mode


def spent(s, ws_id: uuid.UUID, since: datetime | None = None) -> float:
    return float(s.scalar(select(func.coalesce(func.sum(EngineUsage.cost_usd), 0.0)).where(EngineUsage.workspace_id == ws_id, EngineUsage.created_at >= (since or month_start()))) or 0.0)


def limit_of(ws: Workspace) -> float | None:
    v = (ws.settings or {}).get("monthly_budget_usd")
    return float(v) if isinstance(v, (int, float)) and v >= 0 else None


def check(engine: str) -> None:
    """Raise EngineDeclined if this month's budget is used up (the caller falls back to the free engine)."""
    from .db import session_scope
    from .engines.llm import EngineDeclined

    with session_scope() as s:
        ws_id = _workspace_id(s, _scope.get())
        ws = s.get(Workspace, ws_id) if ws_id else None
        if ws is None:
            return
        lim = limit_of(ws)
        if lim is not None and spent(s, ws.id) >= lim:
            raise EngineDeclined(f"this month's budget for paid engines (${lim:.2f}) is used up")


def claude_cost(input_tokens: int, output_tokens: int) -> float:
    st = get_settings()
    return input_tokens / 1e6 * st.claude_price_input_per_mtok + output_tokens / 1e6 * st.claude_price_output_per_mtok


def charge(engine: str, input_tokens: int, output_tokens: int, cost: float) -> None:
    """Record a paid call. Never raises: metering must not lose the work it measures."""
    import logging

    from .db import session_scope
    from .notify import notify

    try:
        with session_scope() as s:
            sc = _scope.get()
            ws_id = _workspace_id(s, sc)
            if ws_id is None:
                return
            before = spent(s, ws_id)
            s.add(EngineUsage(workspace_id=ws_id, engine=engine, stage=(sc.stage if sc else "") or "other", input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost, video_id=sc.video_id if sc else None))
            ws = s.get(Workspace, ws_id)
            lim = limit_of(ws) if ws else None
            if lim:
                after = before + cost
                warn = float((ws.settings or {}).get("budget_warn_pct") or 80) / 100
                month = month_start().strftime("%Y-%m")
                if after >= lim > before:
                    notify(s, ws_id, "budget", "Paid engine budget used up", f"${after:.2f} of ${lim:.2f} this month. Free engines take over until next month or until you raise the budget.", "/engines", "warn", dedupe=f"budget:100:{ws_id}:{month}")
                elif after >= lim * warn > before:
                    notify(s, ws_id, "budget", f"{int(warn * 100)}% of this month's budget used", f"${after:.2f} of ${lim:.2f} spent on paid engines.", "/engines", dedupe=f"budget:warn:{ws_id}:{month}")
    except Exception:
        logging.getLogger("clipstar.budget").exception("couldn't record engine usage")


def summary(s, ws: Workspace) -> dict:
    start = month_start()
    rows = s.execute(
        select(EngineUsage.engine, EngineUsage.stage, func.count(), func.sum(EngineUsage.cost_usd), func.sum(EngineUsage.input_tokens), func.sum(EngineUsage.output_tokens))
        .where(EngineUsage.workspace_id == ws.id, EngineUsage.created_at >= start)
        .group_by(EngineUsage.engine, EngineUsage.stage)
    ).all()
    total = sum(float(r[3] or 0) for r in rows)
    lim = limit_of(ws)
    return {
        "month_start": start.isoformat(),
        "spent_usd": round(total, 4),
        "limit_usd": lim,
        "warn_pct": int((ws.settings or {}).get("budget_warn_pct") or 80),
        "remaining_usd": round(max(0.0, lim - total), 4) if lim is not None else None,
        "blocked": lim is not None and total >= lim,
        "by_engine": [{"engine": e, "stage": st, "calls": n, "cost_usd": round(float(c or 0), 4), "input_tokens": int(i or 0), "output_tokens": int(o or 0)} for e, st, n, c, i, o in rows],
        "prices": {"claude_input_per_mtok": get_settings().claude_price_input_per_mtok, "claude_output_per_mtok": get_settings().claude_price_output_per_mtok},
        "note": "Estimates from token counts and the prices set in CLIPSTAR_CLAUDE_PRICE_*; your provider's bill is the final word.",
    }
