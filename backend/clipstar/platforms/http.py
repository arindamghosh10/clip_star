"""HTTP calls to platforms with consistent error mapping. Tests swap the transport."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from ..errors import PermanentError, RetryableError
from .base import Ambiguous, AuthExpired

_transport: httpx.BaseTransport | None = None  # set by tests


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


def client() -> httpx.Client:
    st = get_settings()
    return httpx.Client(timeout=httpx.Timeout(st.platform_timeout_seconds, connect=20.0), transport=_transport, follow_redirects=False)


def _message(r: httpx.Response) -> str:
    try:
        d = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(d, dict):
        e = d.get("error")
        if isinstance(e, dict):
            return str(e.get("message") or e.get("error_user_msg") or e.get("code") or e)[:300]
        if isinstance(e, str):
            return str(d.get("error_description") or d.get("message") or e)[:300]
        for k in ("message", "detail", "title", "error_description"):
            if d.get(k):
                return str(d[k])[:300]
        errs = d.get("errors")
        if isinstance(errs, list) and errs:
            return str(errs[0].get("message") if isinstance(errs[0], dict) else errs[0])[:300]
    return r.text[:300]


def call(method: str, url: str, *, label: str, commit: bool = False, ok: tuple[int, ...] = (200, 201, 202, 204), **kw: Any) -> httpx.Response:
    """One platform request.

    commit=True marks the request that creates the post: a timeout there is Ambiguous
    (it may have worked), not Retryable.
    """
    try:
        with client() as c:
            r = c.request(method, url, **kw)
    except httpx.TimeoutException as e:
        if commit:
            raise Ambiguous(str(e), user_message=f"{label} didn't answer in time; the post may or may not exist. Checking before any retry.") from e
        raise RetryableError(str(e), user_message=f"{label} timed out; will retry.") from e
    except httpx.TransportError as e:
        # connection failed before a response: for a commit call we can't be sure the request wasn't processed
        if commit and not isinstance(e, httpx.ConnectError):
            raise Ambiguous(str(e), user_message=f"Lost the connection to {label}; checking whether the post was created.") from e
        raise RetryableError(str(e), user_message=f"Couldn't reach {label}; will retry.") from e
    if r.status_code in ok:
        return r
    msg = _message(r)
    if r.status_code == 401:
        raise AuthExpired(msg, user_message=f"{label} login expired or was revoked. Reconnect the account.")
    if r.status_code == 429:
        raise RetryableError(msg, user_message=f"{label} rate limit reached; will retry later.")
    if r.status_code >= 500:
        if commit:
            raise Ambiguous(msg, user_message=f"{label} had a server error while publishing; checking whether the post was created.")
        raise RetryableError(msg, user_message=f"{label} had a server error; will retry.")
    if r.status_code == 403:
        raise PermanentError(msg, user_message=f"{label} refused: {msg}. Check the app's permissions/approval for this account.")
    raise PermanentError(msg, user_message=f"{label} rejected the request: {msg}")


def json_of(r: httpx.Response, label: str) -> dict:
    try:
        d = r.json()
    except ValueError as e:
        raise PermanentError(r.text[:200], user_message=f"{label} returned an unexpected response.") from e
    return d if isinstance(d, dict) else {"data": d}
