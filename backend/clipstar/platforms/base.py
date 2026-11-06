"""Contract every platform follows, and the error types the publisher understands.

Error meaning for the publisher:
- AuthExpired       login no longer valid -> account marked "reconnect", post fails with that reason
- RetryableError    temporary, nothing was created on the platform -> safe to try again later
- Ambiguous         the platform may have created the post (e.g. timeout on the final call)
                    -> post becomes "unknown" and is verified, never blindly re-posted
- PermanentError    retrying won't help (rejected video, missing permission)
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ClipstarError


class AuthExpired(ClipstarError):
    retryable = False


class Ambiguous(ClipstarError):
    retryable = False


@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None  # epoch seconds
    extra: dict = field(default_factory=dict)

    def expiring(self, within_s: float = 300) -> bool:
        return self.expires_at is not None and self.expires_at - time.time() < within_s

    def to_dict(self) -> dict:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_at": self.expires_at, "extra": self.extra}

    @classmethod
    def from_dict(cls, d: dict) -> "Tokens":
        return cls(d["access_token"], d.get("refresh_token"), d.get("expires_at"), d.get("extra") or {})

    @classmethod
    def from_oauth(cls, data: dict, **extra) -> "Tokens":
        exp = data.get("expires_in")
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + float(exp) if exp else None,
            extra={k: v for k, v in extra.items() if v is not None},
        )


@dataclass
class Identity:
    """One postable account found after login (a login can unlock several, e.g. Facebook Pages)."""

    remote_id: str
    handle: str
    tokens: Tokens
    options: dict = field(default_factory=dict)


@dataclass
class App:
    client_id: str
    client_secret: str


@dataclass
class PublishRequest:
    video: Path
    cover: Path | None
    title: str
    caption: str  # full post text (caption + hashtags)
    hashtags: list[str]
    duration_s: float
    post_id: str
    account_options: dict = field(default_factory=dict)


@dataclass
class PublishResult:
    remote_id: str
    url: str | None = None
    note: str | None = None  # shown on the post, e.g. "posted privately"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class Provider:
    platform: str
    label: str
    scopes: list[str] = []
    docs_url: str = ""
    # how the platform wants the app's client id/secret labelled in setup
    client_id_label: str = "Client ID"

    def auth_url(self, app: App, state: str, redirect_uri: str, code_challenge: str) -> str:
        raise NotImplementedError

    def exchange(self, app: App, code: str, redirect_uri: str, verifier: str) -> Tokens:
        raise NotImplementedError

    def identities(self, app: App, tokens: Tokens) -> list[Identity]:
        raise NotImplementedError

    def refresh(self, app: App, tokens: Tokens) -> Tokens | None:
        """New tokens, or None if this platform's tokens can't be refreshed (user must reconnect when expired)."""
        return None

    def publish(self, app: App, tokens: Tokens, remote_id: str, req: PublishRequest) -> PublishResult:
        raise NotImplementedError

    def find(self, app: App, tokens: Tokens, remote_id: str, req: PublishRequest, since: float) -> PublishResult | None:
        """Look for a post we may already have created (used after an ambiguous failure). None = not found / can't tell."""
        return None
