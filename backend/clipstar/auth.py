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


def new_session(s: Session, user: User, user_agent: str = "") -> str:
    raw = secrets.token_urlsafe(32)
    s.add(UserSession(user_id=user.id, token_hash=token_hash(raw), expires_at=now() + timedelta(days=get_settings().session_days), user_agent=user_agent[:300]))
    user.last_login_at = now()
    return raw


def session_user(s: Session, raw: str | None) -> User | None:
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
    return user


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


# ---------- permissions ----------


@dataclass
class Principal:
    role: Role
    user: User | None = None
    via: str = "session"  # session | token | open

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None


_SAFE = {"GET", "HEAD", "OPTIONS"}
# Paths anyone signed in may change (their own profile, notifications)
_SELF = [r"^/api/auth/", r"^/api/notifications(/|$)"]
# What reviewers may do besides looking: approve/reject and fix clips, approve or stop batches and posts, handle comments.
_REVIEWER = [r"^/api/clips/[^/]+$", r"^/api/batches/[^/]+/(approve|disable|enable|cancel)$", r"^/api/posts/[^/]+/cancel$", r"^/api/comments(/|$)"]
# Owner only: team, platform developer apps, paid engine choice, budgets, storage policy and backups.
_OWNER = [r"^/api/users(/|$)", r"^/api/platforms/[^/]+/app$", r"^/api/engines/", r"^/api/admin/"]

ROLE_HELP = {
    Role.owner: "Everything, including the team, platform apps, paid engines, budgets, storage and backups.",
    Role.editor: "Add videos, edit clips, schedule and publish, connect accounts, change creator settings.",
    Role.reviewer: "Approve or reject clips, approve or stop batches, and handle comments.",
    Role.viewer: "Look at everything, change nothing.",
}


# Owner only even to read: backup files contain the encryption key.
_OWNER_READ = [r"^/api/admin/backups/[^/]+$"]


def allowed(role: Role, method: str, path: str) -> bool:
    if role != Role.owner and any(re.search(p, path) for p in _OWNER_READ):
        return False
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
