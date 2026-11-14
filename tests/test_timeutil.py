"""App clock: IST wall-clock by default, overrideable for other zones."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from remo import timeutil as T


def test_now_is_ist_wall_clock() -> None:
    before = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    got = T.now()
    after = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    assert before <= got <= after
    assert got.tzinfo is None, "naive wall-clock keeps old comparisons working"


def test_from_ts_converts_epoch_to_ist_wall() -> None:
    ts = 1730000000.0
    expected = (
        datetime.fromtimestamp(ts, timezone.utc)
        .astimezone(ZoneInfo("Asia/Kolkata"))
        .replace(tzinfo=None)
    )
    assert T.from_ts(ts) == expected
    assert T.from_ts(ts).tzinfo is None


def test_timezone_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMO_TIMEZONE", "UTC")
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    got = T.now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert before <= got <= after


def test_invalid_timezone_falls_back_to_ist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMO_TIMEZONE", "Bogus/Zone")
    before = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    got = T.now()
    after = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    assert before <= got <= after
