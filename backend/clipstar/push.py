"""Push notifications to phones and browsers (Web Push: RFC 8030 delivery, RFC 8291 encryption, RFC 8292 VAPID).

No third-party push account is needed: the browser's own push service (Google, Mozilla, Apple, Microsoft)
delivers the message, and only the subscribed device can decrypt it.
On iPhone/iPad, push works once clip_star is added to the Home Screen (iOS 16.4+).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlparse

import http_ece
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from sqlalchemy import delete, select

from .config import get_settings

log = logging.getLogger("clipstar.push")
KIND = "notify.push"

# Only real browser push services, so a subscription can't be used to make this server call internal addresses.
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com", "updates.push.services.mozilla.com",
    "push.apple.com", "notify.windows.com",
)

DEFAULT_PUSH_KINDS = ["needs_approval", "post_problem", "reconnect", "video_failed", "lead", "budget", "storage", "backup", "webhook"]

_transport: httpx.BaseTransport | None = None  # tests swap in a fake push service


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@lru_cache
def _key() -> ec.EllipticCurvePrivateKey:
    st = get_settings()
    pem = st.vapid_private_key
    if not pem:
        path = st.storage_dir.resolve() / ".vapid_key"
        if path.exists():
            pem = path.read_text()
        else:
            k = ec.generate_private_key(ec.SECP256R1())
            pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(pem)
            except FileExistsError:  # another process made it first: use theirs
                pem = path.read_text()
    return serialization.load_pem_private_key(pem.encode(), password=None)


def public_key() -> str:
    """The VAPID public key, as browsers want it for `applicationServerKey`."""
    raw = _key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64url(raw)


def _subject() -> str:
    st = get_settings()
    if st.vapid_subject:
        return st.vapid_subject
    if st.web_url.startswith("https://"):
        return st.web_url
    return "mailto:clipstar@" + (urlparse(st.web_url).hostname or "localhost")


def vapid_header(endpoint: str, now: int | None = None) -> str:
    u = urlparse(endpoint)
    now = int(time.time()) if now is None else now
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64url(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": now + 12 * 3600, "sub": _subject()}, separators=(",", ":")).encode())
    signing = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(_key().sign(signing, ec.ECDSA(hashes.SHA256())))
    sig = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={public_key()}"


def check_endpoint(endpoint: str) -> str:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in PUSH_HOST_SUFFIXES):
        raise ValueError("That isn't a browser push service address.")
    return endpoint


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """aes128gcm body for one subscription; a fresh key per message."""
    return http_ece.encrypt(payload, private_key=ec.generate_private_key(ec.SECP256R1()), dh=unb64url(p256dh), auth_secret=unb64url(auth), version="aes128gcm")


def send(sub, message: dict, urgency: str = "normal", ttl: int = 86400) -> int:
    """Send one message to one subscription. Returns the HTTP status (201 = accepted)."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub.p256dh, sub.auth)
    headers = {"TTL": str(ttl), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "Urgency": urgency, "Authorization": vapid_header(sub.endpoint)}
    with httpx.Client(timeout=15, transport=_transport, follow_redirects=False) as c:
        return c.post(sub.endpoint, content=body, headers=headers).status_code


def deliver_to_users(s, user_ids: list[uuid.UUID], message: dict, urgency: str = "normal") -> dict:
    """Send to every device of these people. Gone subscriptions (404/410) are removed; others just log."""
    from .models import PushSubscription

    out = {"sent": 0, "removed": 0, "failed": 0}
    for sub in list(s.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))):
        try:
            code = send(sub, message, urgency)
        except (httpx.HTTPError, ValueError) as e:
            log.info("push to %s failed: %s", urlparse(sub.endpoint).hostname, e)
            code = None
        if code in (404, 410):  # unsubscribed or expired on the device
            s.delete(sub)
            out["removed"] += 1
        elif code is not None and 200 <= code < 300:
            sub.last_success_at, sub.failures = datetime.now(timezone.utc), 0
            out["sent"] += 1
        else:
            sub.failures += 1
            out["failed"] += 1
            if sub.failures >= 20:
                s.delete(sub)
    return out


# ---------- notifications -> push ----------


def recipients(s, ws_id: uuid.UUID, kind: str) -> list[uuid.UUID]:
    from .models import Membership, User

    out = []
    for uid, prefs in s.execute(
        select(Membership.user_id, Membership.prefs).join(User, User.id == Membership.user_id).where(Membership.workspace_id == ws_id, Membership.disabled.is_(False), User.disabled.is_(False))
    ):
        prefs = prefs or {}
        if prefs.get("push", True) and kind in prefs.get("push_kinds", DEFAULT_PUSH_KINDS):
            out.append(uid)
    return out


def dispatch() -> int:
    """Queue a push job for each new notification (last 6 hours only, so old news isn't pushed)."""
    from .db import session_scope
    from .jobs import queue
    from .models import Notification, PushSubscription

    with session_scope() as s:
        if not s.scalar(select(PushSubscription.id).limit(1)):
            return 0
        n = 0
        for nt in s.scalars(select(Notification).where(Notification.pushed_at.is_(None), Notification.created_at > datetime.now(timezone.utc) - timedelta(hours=6)).limit(50)):
            queue.enqueue(s, KIND, {"id": str(nt.id)}, dedupe_key=f"push:{nt.id}", priority=55, max_attempts=2)
            n += 1
        return n


def run_push(ctx) -> dict:
    from .db import session_scope
    from .models import Notification, Workspace

    with session_scope() as s:
        nt = s.get(Notification, uuid.UUID(ctx.payload["id"]), with_for_update=True)
        if nt is None or nt.pushed_at is not None:
            return {"skipped": True}
        nt.pushed_at = datetime.now(timezone.utc)  # best effort: never push the same thing twice
        users = recipients(s, nt.workspace_id, nt.kind)
        ws = s.get(Workspace, nt.workspace_id)
        link = nt.link or "/"
        link += ("&" if "?" in link else "?") + f"ws={nt.workspace_id}"  # opens in the right workspace
        msg = {"title": nt.title, "body": nt.body[:300], "url": link, "tag": f"{nt.kind}:{nt.id}", "workspace": ws.name if ws else ""}
        res = deliver_to_users(s, users, msg, "high" if nt.severity == "error" else "normal") if users else {"sent": 0}
    return res


def register_handlers() -> None:
    from .jobs.runtime import Handler, register

    register(KIND, Handler(run=run_push))


def purge_dead(s) -> int:
    from .models import PushSubscription

    return s.execute(delete(PushSubscription).where(PushSubscription.failures >= 20)).rowcount
