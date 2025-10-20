# app/utils/time.py
from __future__ import annotations
from datetime import datetime, date, time, timedelta, timezone
import os

# Optional: test/ops can set this to freeze "now" (ISO 8601, e.g. 2025-10-13T09:05:00Z)
UTC_NOW_OVERRIDE_ENV = "UTC_NOW_OVERRIDE"

def now_utc() -> datetime:
    """
    Single source of truth for current time in UTC.
    If env UTC_NOW_OVERRIDE is set (ISO 8601 string), use it.
    """
    v = os.getenv(UTC_NOW_OVERRIDE_ENV)
    if v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            # if malformed, ignore and fall through to real clock
            pass
    return datetime.now(timezone.utc)

def today_utc() -> date:
    """UTC calendar date for 'today'."""
    return now_utc().date()

def time_after_utc(minutes: int) -> time:
    """UTC wall-clock time after 'minutes' from now."""
    return (now_utc() + timedelta(minutes=minutes)).time()
