"""Things that happened, recorded in order (the `events` table). Webhooks and the /api/events feed read them.

Events are written by the same database hook as notifications (see notify.py), in the same transaction
as the change itself, so an event exists exactly when the change was saved.
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.orm import Session

from .models import Event

EVENT_TYPES: dict[str, str] = {
    "video.ready": "A video finished processing; clips are ready for review",
    "video.failed": "A video stopped processing",
    "clip.approved": "A clip was approved",
    "clip.rejected": "A clip was rejected",
    "batch.awaiting_approval": "A batch of posts is waiting for approval",
    "batch.approved": "A batch was approved and will post on schedule",
    "post.published": "A post went live on a platform",
    "post.failed": "A post failed or couldn't be confirmed",
    "account.needs_reconnect": "An account's login expired",
    "comment.received": "A new comment arrived on one of your posts",
    "report.ready": "A weekly report was made",
}


def emit(s: Session, ws_id: uuid.UUID, type_: str, data: dict) -> None:
    """Record an event. Raw insert, so it's safe inside a flush."""
    s.connection().execute(insert(Event).values(workspace_id=ws_id, type=type_, data=_jsonable(data)))


def _jsonable(d):
    if isinstance(d, dict):
        return {k: _jsonable(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_jsonable(v) for v in d]
    if isinstance(d, uuid.UUID):
        return str(d)
    if hasattr(d, "isoformat"):
        return d.isoformat()
    if hasattr(d, "value"):
        return d.value
    return d
