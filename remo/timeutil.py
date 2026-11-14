"""App clock: one wall-clock for the whole backend.

Servers (Railway, containers) run on UTC while users live in IST, so every
"what time is it" read goes through here. IST by default, REMO_TIMEZONE
overrides. Naive datetimes throughout: the zone only decides which wall
clock we read, and naive keeps every existing comparison and test intact.
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE = "Asia/Kolkata"


def zone() -> ZoneInfo:
    """App timezone, falling back to IST when unset or invalid."""
    try:
        return ZoneInfo(os.environ.get("REMO_TIMEZONE", DEFAULT_ZONE))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_ZONE)


def now() -> datetime:
    """Current wall-clock in the app timezone (naive)."""
    return datetime.now(zone()).replace(tzinfo=None)


def from_ts(ts: float) -> datetime:
    """Epoch seconds to app-timezone wall-clock (naive).

    datetime.fromtimestamp uses the SERVER zone, which is wrong on UTC hosts.
    """
    return datetime.fromtimestamp(ts, tz=zone()).replace(tzinfo=None)


def epoch(when: datetime) -> float:
    """Naive app-zone wall-clock back to epoch seconds."""
    return when.replace(tzinfo=zone()).timestamp()


def time() -> float:
    """Epoch seconds (zone-independent, alias for readability at call sites)."""
    return _time.time()
