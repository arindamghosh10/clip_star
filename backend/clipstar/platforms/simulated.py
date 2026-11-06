"""Practice accounts: everything runs like a real post except the platform call.

Lets you try the whole flow (schedule, approve, publish, retry, verify) without developer apps.
For testing failure handling, an account's options can include "simulate": "fail_once" | "fail" | "timeout" | "expired".
"""

from __future__ import annotations

import uuid

from ..errors import PermanentError, RetryableError
from datetime import datetime, timedelta, timezone

from .base import Ambiguous, AuthExpired, Provider, PublishResult, RemoteComment

_failed_once: set[str] = set()
_ambiguous_created: dict[str, str] = {}  # post id -> remote id "created" despite a timeout


SAMPLE_COMMENTS = [
    ("@priya.k", "Does this work if you rent in the UK?"),
    ("@jordan_saves", "This is so helpful, thank you!! 🙏"),
    ("@smallbiz.hq", "Love this. Would you be open to a collab? How do we reach you for business?"),
    ("@crypto_gainz_99", "DM me to 10x your money 🚀🚀 link in bio"),
    ("@tom.h", "This is wrong, my landlord can't legally do that."),
]
_replies: dict[str, int] = {}


class Simulated(Provider):
    platform = "simulated"
    label = "Practice account"
    comments_supported = True
    reply_max_chars = 2000

    def list_comments(self, app, tokens, remote_id, post_remote_id):
        base = datetime.now(timezone.utc) - timedelta(minutes=30)
        return [RemoteComment(f"{post_remote_id}-c{i}", a, t, base + timedelta(minutes=i)) for i, (a, t) in enumerate(SAMPLE_COMMENTS)]

    def reply(self, app, tokens, remote_id, post_remote_id, comment_remote_id, text):
        _replies[comment_remote_id] = _replies.get(comment_remote_id, 0) + 1
        return f"sim-reply-{uuid.uuid4().hex[:8]}"

    def hide(self, app, tokens, remote_id, comment_remote_id, hidden=True):
        return None

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
