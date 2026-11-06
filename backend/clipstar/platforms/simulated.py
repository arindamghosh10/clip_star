"""Practice accounts: everything runs like a real post except the platform call.

Lets you try the whole flow (schedule, approve, publish, retry, verify) without developer apps.
For testing failure handling, an account's options can include "simulate": "fail_once" | "fail" | "timeout" | "expired".
"""

from __future__ import annotations

import uuid

from ..errors import PermanentError, RetryableError
from .base import Ambiguous, AuthExpired, Provider, PublishResult

_failed_once: set[str] = set()
_ambiguous_created: dict[str, str] = {}  # post id -> remote id "created" despite a timeout


class Simulated(Provider):
    platform = "simulated"
    label = "Practice account"

    def publish(self, app, tokens, remote_id, req):
        mode = req.account_options.get("simulate")
        if mode == "fail":
            raise PermanentError("simulated", user_message="Practice account set to always fail.")
        if mode == "fail_once" and req.post_id not in _failed_once:
            _failed_once.add(req.post_id)
            raise RetryableError("simulated", user_message="Practice account: temporary failure (will retry).")
        if mode == "expired":
            raise AuthExpired("simulated", user_message="Practice account: login expired. Reconnect the account.")
        if mode == "timeout":
            # pretend the platform created the post but the answer got lost
            _ambiguous_created[req.post_id] = f"sim-{uuid.uuid4().hex[:10]}"
            raise Ambiguous("simulated", user_message="Practice account: no answer from the platform; checking before any retry.")
        return PublishResult(f"sim-{uuid.uuid4().hex[:10]}", None)

    def find(self, app, tokens, remote_id, req, since):
        rid = _ambiguous_created.get(req.post_id)
        return PublishResult(rid, None) if rid else None
