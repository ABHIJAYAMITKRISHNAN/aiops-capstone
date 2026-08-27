"""Small shared helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_correlation_id() -> str:
    return str(uuid.uuid4())
