"""Team sign-in: passwords, sessions, invites and what each role may do.

- Passwords are hashed with scrypt (random salt per user).
- A session is a random cookie value; only its SHA-256 is stored, so a database leak doesn't hand out logins.
- Until the first owner is created (setup), and if no API token is set, the API is open so the setup wizard can run.
- The CLIPSTAR_API_TOKEN still works for scripts and automation, with owner rights.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Role, User, UserSession

COOKIE = "clipstar_session"
CSRF_HEADER = "x-clipstar"

_N, _R, _P = 2**14, 8, 1


def now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        # same work as a real check, so timing doesn't reveal which emails exist
        hashlib.scrypt(pw.encode(), salt=b"0" * 16, n=_N, r=_R, p=_P, dklen=32)
        return False
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


def password_problem(pw: str) -> str | None:
    if len(pw) < 10:
        return "Use at least 10 characters."
    if len(pw) > 200:
        return "That password is too long."
    if pw.lower() in {"password12", "1234567890", "qwertyuiop", "clipstar123"}:
        return "That password is too common."
    return None


def normalize_email(e: str) -> str:
    return e.strip().lower()


def valid_email(e: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e)) and len(e) <= 320


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def users_exist(s: Session) -> bool:
    return bool(s.scalar(select(func.count(User.id))))


def new_session(s: Session, user: User, user_agent: str = "", workspace_id: uuid.UUID | None = None) -> str:
    raw = secrets.token_urlsafe(32)
    if workspace_id is None:
        m = membership(s, user.id)
        workspace_id = m.workspace_id if m else None
    s.add(UserSession(user_id=user.id, workspace_id=workspace_id, token_hash=token_hash(raw), expires_at=now() + timedelta(days=get_settings().session_days), user_agent=user_agent[:300]))
    user.last_login_at = now()
    return raw


def session_row(s: Session, raw: str | None) -> tuple[UserSession, User] | None:
    if not raw:
        return None
    sess = s.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw)))
    if sess is None or sess.expires_at < now():
        return None
    user = s.get(User, sess.user_id)
    if user is None or user.disabled or not user.password_hash:
        return None
    if sess.last_seen_at < now() - timedelta(hours=1):  # sliding expiry, written at most hourly
        sess.last_seen_at = now()
        sess.expires_at = now() + timedelta(days=get_settings().session_days)
        s.commit()
    return sess, user


def session_user(s: Session, raw: str | None) -> User | None:
    r = session_row(s, raw)
    return r[1] if r else None


def membership(s: Session, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None):
    """The person's active membership in that workspace, or (without one) their first active membership."""
    from .models import Membership

    q = select(Membership).where(Membership.user_id == user_id, Membership.disabled.is_(False))
    if workspace_id is not None:
        m = s.scalar(q.where(Membership.workspace_id == workspace_id))
        if m is not None:
            return m
    return s.scalar(q.order_by(Membership.created_at).limit(1))


def memberships(s: Session, user_id: uuid.UUID) -> list:
    from .models import Membership

    return list(s.scalars(select(Membership).where(Membership.user_id == user_id, Membership.disabled.is_(False)).order_by(Membership.created_at)))


def end_sessions(s: Session, user_id: uuid.UUID, keep_hash: str | None = None) -> None:
    for sess in s.scalars(select(UserSession).where(UserSession.user_id == user_id)):
        if sess.token_hash != keep_hash:
            s.delete(sess)


def new_invite(user: User) -> str:
    raw = secrets.token_urlsafe(24)
    user.invite_hash = token_hash(raw)
    user.invite_expires_at = now() + timedelta(days=7)
    return raw


def invite_url(raw: str) -> str:
    return f"{get_settings().web_url.rstrip('/')}/invite?token={raw}"


def find_invite(s: Session, raw: str) -> User | None:
    u = s.scalar(select(User).where(User.invite_hash == token_hash(raw)))
    if u is None or u.disabled or not u.invite_expires_at or u.invite_expires_at < now():
        return None
    return u


# ---------- personal API keys ----------

KEY_PREFIX = "cs_"
RANK = {Role.viewer: 0, Role.reviewer: 1, Role.editor: 2, Role.owner: 3}


def new_api_key() -> tuple[str, str, str]:
    """Returns (raw key shown once, display prefix, hash stored)."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:10], token_hash(raw)


def lower_role(a: Role, b: Role) -> Role:
    return a if RANK[a] <= RANK[b] else b


_hits: dict[str, list[float]] = {}


def rate_ok(key_id: str, per_minute: int) -> bool:
    """Sliding one-minute window per key, in this process."""
    import time as _t

    t = _t.monotonic()
    q = [x for x in _hits.get(key_id, []) if t - x < 60]
    if len(q) >= per_minute:
        _hits[key_id] = q
        return False
    q.append(t)
    _hits[key_id] = q
    return True


def key_principal(s: Session, raw: str):
    from .models import ApiKey

    k = s.scalar(select(ApiKey).where(ApiKey.key_hash == token_hash(raw)))
    if k is None or k.revoked_at is not None:
        return None
    u = s.get(User, k.user_id)
    if u is None or u.disabled or not u.password_hash:
        return None
    from .models import Membership

    m = s.scalar(select(Membership).where(Membership.user_id == u.id, Membership.workspace_id == k.workspace_id, Membership.disabled.is_(False)))
    if m is None:  # removed from the key's workspace
        return None
    if k.last_used_at is None or k.last_used_at < now() - timedelta(minutes=5):
        k.last_used_at = now()
        s.commit()
    return Principal(lower_role(k.role, m.role), user=u, via="key", key_id=str(k.id), workspace_id=k.workspace_id, membership=m)


# ---------- permissions ----------


@dataclass
class Principal:
    role: Role
    user: User | None = None
    via: str = "session"  # session | key | token | open
    key_id: str | None = None
    workspace_id: uuid.UUID | None = None
    membership: object | None = None
    session: object | None = None

    @property
    def admin(self) -> bool:
        """Looks after the whole server (backups). The API token and first-run setup count as admin."""
        return self.user is None or bool(self.user.is_admin)

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None


_SAFE = {"GET", "HEAD", "OPTIONS"}
# Paths anyone signed in may change (their own profile, notifications)
_SELF = [r"^/api/auth/", r"^/api/notifications(/|$)", r"^/api/keys(/|$)", r"^/api/workspaces(/|$)", r"^/api/push(/|$)"]  # workspace routes check ownership themselves
# What reviewers may do besides looking: approve/reject and fix clips, approve or stop batches and posts, handle comments.
_REVIEWER = [r"^/api/clips/[^/]+$", r"^/api/batches/[^/]+/(approve|disable|enable|cancel)$", r"^/api/posts/[^/]+/cancel$", r"^/api/comments(/|$)"]
# Owner only: team, platform developer apps, paid engine choice, budgets, storage policy and backups.
_OWNER = [r"^/api/users(/|$)", r"^/api/platforms/[^/]+/app$", r"^/api/engines/", r"^/api/admin/", r"^/api/webhooks(/|$)"]

ROLE_HELP = {
    Role.owner: "Everything, including the team, platform apps, paid engines, budgets, storage and backups.",
    Role.editor: "Add videos, edit clips, schedule and publish, connect accounts, change creator settings.",
    Role.reviewer: "Approve or reject clips, approve or stop batches, and handle comments.",
    Role.viewer: "Look at everything, change nothing.",
}


# Server-wide, so for the instance admin only (backups even to read: they contain the encryption key).
ADMIN_ONLY = [r"^/api/admin/backups(/|$)", r"^/api/admin/storage/clean$"]


def allowed(role: Role, method: str, path: str) -> bool:
    if method in _SAFE or any(re.search(p, path) for p in _SELF):
        return True
    if role == Role.owner:
        return True
    if any(re.search(p, path) for p in _OWNER):
        return False
    if role == Role.editor:
        return True
    if role == Role.reviewer:
        return any(re.search(p, path) for p in _REVIEWER)
    return False


def denied_message(role: Role) -> str:
    return {
        Role.viewer: "Your role is Viewer: you can look but not change things. Ask an owner for more access.",
        Role.reviewer: "Your role is Reviewer: you can approve clips, batches and replies, but not this. Ask an owner for more access.",
        Role.editor: "Only an owner can do this.",
    }.get(role, "Not allowed.")
