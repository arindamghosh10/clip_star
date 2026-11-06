from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlencode

from ..errors import PermanentError

sleep: Callable[[float], None] = time.sleep  # replaced in tests


def url(base: str, **params) -> str:
    return f"{base}?{urlencode({k: v for k, v in params.items() if v is not None})}"


def bearer(tokens) -> dict:
    return {"Authorization": f"Bearer {tokens.access_token}"}


def wait_until(check: Callable[[], str | None], *, label: str, every: float = 5.0, timeout: float = 900.0) -> str:
    """Poll `check` until it returns a non-None value. Raises after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        v = check()
        if v is not None:
            return v
        if time.monotonic() > deadline:
            raise PermanentError("processing timeout", user_message=f"{label} took too long to process the video.")
        sleep(every)


def text_matches(a: str | None, b: str | None, n: int = 60) -> bool:
    norm = lambda s: " ".join((s or "").split())[:n].lower()  # noqa: E731
    return bool(a) and bool(b) and norm(a) == norm(b)
