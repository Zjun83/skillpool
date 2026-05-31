"""Time utilities — timezone-aware UTC helpers."""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware).

    Replaces datetime.utcnow() which is deprecated and returns naive datetimes.
    """
    return datetime.now(timezone.utc)
