"""Webhooks: POST each event to the URLs that asked for it, signed, retried, and never to internal addresses.

Each request carries:
  X-ClipStar-Event:      the event type, e.g. post.published
  X-ClipStar-Delivery:   a unique id (use it to ignore duplicates; retries reuse it)
  X-ClipStar-Signature:  t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<raw body>" with the webhook's secret>

Receivers should answer 2xx within 10 seconds. Anything else is retried with growing gaps (about 6 tries);
after 20 failed deliveries in a row the webhook is switched off and the owners are notified.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .errors import PermanentError, RetryableError
from .jobs import queue
from .jobs.runtime import Handler, JobContext, register
from .models import Event, Webhook, WebhookDelivery
from .secrets import decrypt, encrypt

log = logging.getLogger("clipstar.webhooks")
KIND = "webhook.deliver"
USER_AGENT = "clip_star-webhooks/1"


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def store_secret(raw: str) -> str:
    return encrypt(raw)


def sign(secret: str, body: bytes, t: int | None = None) -> str:
    t = int(time.time()) if t is None else t
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    """Reference check for receivers (also used in tests)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - t) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, body, t), header)


# ---------- URL safety ----------


def check_url(url: str) -> str:
    """Validate the shape of a webhook URL (scheme, host, no credentials). Returns the cleaned URL."""
    url = url.strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Use a full http:// or https:// address.")
    if u.username or u.password:
        raise ValueError("Don't put a username or password in the address; the signature proves who's calling.")
    if len(url) > 2000:
        raise ValueError("That address is too long.")
    if not get_settings().webhook_allow_private:
        try:
            ip = ipaddress.ip_address(u.hostname)
        except ValueError:
            ip = None
        if (ip and not ip.is_global) or u.hostname.lower() in ("localhost",) or u.hostname.lower().endswith((".local", ".internal", ".localhost")):
            raise ValueError("Internal addresses are blocked. To send to a service on your own network, set CLIPSTAR_WEBHOOK_ALLOW_PRIVATE=true.")
    return url


def _resolves_public(host: str, port: int) -> None:
    """At send time: every address the name resolves to must be public (unless private addresses are allowed)."""
    if get_settings().webhook_allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise RetryableError(str(e), user_message=f"Couldn't look up {host}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise PermanentError(f"{host} -> {ip}", user_message=f"{host} points to an internal address ({ip}); blocked. Set CLIPSTAR_WEBHOOK_ALLOW_PRIVATE=true to allow it.")


# ---------- fan-out and delivery ----------


def payload(ev: Event) -> dict:
    return {"id": ev.id, "type": ev.type, "created_at": ev.created_at.isoformat() if ev.created_at else None, "workspace_id": str(ev.workspace_id), "data": ev.data}


def wants(h: Webhook, type_: str) -> bool:
    ev = h.events or []
    return "*" in ev or type_ in ev


def dispatch(limit: int = 200) -> int:
    """Turn new events into deliveries (one per matching webhook) and queue them. Safe to run from many workers."""
    n = 0
    with session_scope() as s:
        events = s.scalars(select(Event).where(Event.fanned_out.is_(False)).order_by(Event.id).limit(limit).with_for_update(skip_locked=True)).all()
        if not events:
            return 0
        hooks: dict[uuid.UUID, list[Webhook]] = {}
        for ev in events:
            if ev.workspace_id not in hooks:
                hooks[ev.workspace_id] = list(s.scalars(select(Webhook).where(Webhook.workspace_id == ev.workspace_id, Webhook.enabled.is_(True))))
            for h in hooks[ev.workspace_id]:
                if wants(h, ev.type):
                    d = WebhookDelivery(id=uuid.uuid4(), webhook_id=h.id, event_id=ev.id, event_type=ev.type)
                    s.add(d)
                    s.flush()
                    queue.enqueue(s, KIND, {"delivery_id": str(d.id)}, dedupe_key=f"wh:{d.id}", priority=70, max_attempts=6)
                    n += 1
            ev.fanned_out = True
    return n


def queue_delivery(s, h: Webhook, ev: Event) -> WebhookDelivery:
    d = WebhookDelivery(id=uuid.uuid4(), webhook_id=h.id, event_id=ev.id, event_type=ev.type)
    s.add(d)
    s.flush()
    queue.enqueue(s, KIND, {"delivery_id": str(d.id)}, dedupe_key=f"wh:{d.id}", priority=40, max_attempts=6)
    return d


def run_deliver(ctx: JobContext) -> dict:
    did = uuid.UUID(ctx.payload["delivery_id"])
    with session_scope() as s:
        d = s.get(WebhookDelivery, did, with_for_update=True)
        if d is None or d.status == "sent":
            return {"skipped": True}
        h = s.get(Webhook, d.webhook_id)
        ev = s.get(Event, d.event_id)
        if h is None or ev is None:
            return {"skipped": True}
        if not h.enabled:
            d.status, d.error = "failed", "Webhook is switched off."
            return {"skipped": "disabled"}
        d.attempts += 1
        url, secret = h.url, decrypt(h.secret_enc)
        body = json.dumps(payload(ev), separators=(",", ":"), ensure_ascii=False).encode()
        etype = ev.type
    u = urlparse(url)
    _resolves_public(u.hostname or "", u.port or (443 if u.scheme == "https" else 80))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-ClipStar-Event": etype,
        "X-ClipStar-Delivery": str(did),
        "X-ClipStar-Signature": sign(secret, body),
    }
    code, err = None, None
    try:
        with httpx.Client(timeout=get_settings().webhook_timeout_seconds, follow_redirects=False) as c:
            r = c.post(url, content=body, headers=headers)
        code = r.status_code
        if not 200 <= code < 300:
            err = f"HTTP {code}: {r.text[:300]}"
    except httpx.HTTPError as e:
        err = f"{type(e).__name__}: {e}"[:500]

    with session_scope() as s:
        d = s.get(WebhookDelivery, did, with_for_update=True)
        h = s.get(Webhook, d.webhook_id, with_for_update=True)
        d.response_code, d.error = code, err
        h.last_delivery_at = now()
        if err is None:
            d.status, d.delivered_at = "sent", now()
            h.consecutive_failures = 0
            return {"sent": code}
    if code is not None and 400 <= code < 500 and code not in (408, 409, 425, 429):
        raise PermanentError(err, user_message=f"The receiver refused the webhook ({err[:120]}).")
    raise RetryableError(err, user_message=f"Webhook delivery failed ({err[:120]}); will retry.")


def _failed(s, job) -> None:
    from .notify import notify

    d = s.get(WebhookDelivery, uuid.UUID(job.payload["delivery_id"]), with_for_update=True)
    if d is None:
        return
    d.status = "failed"
    d.error = d.error or job.last_error
    h = s.get(Webhook, d.webhook_id, with_for_update=True)
    if h is None:
        return
    h.consecutive_failures += 1
    limit = get_settings().webhook_disable_after_failures
    if h.enabled and h.consecutive_failures >= limit:
        h.enabled = False
        h.disabled_reason = f"Switched off after {limit} failed deliveries in a row. Last error: {(d.error or '')[:150]}"
        notify(s, h.workspace_id, "webhook", "A webhook was switched off", f"{h.url}: {h.disabled_reason}", "/settings#integrations", "warn", dedupe=f"webhook_off:{h.id}:{now():%Y%m%d%H}")


def register_handlers() -> None:
    register(KIND, Handler(run=run_deliver, on_failure=_failed))
