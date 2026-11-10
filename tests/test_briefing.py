"""Day's plan: composition, query detection, daily schedule setting."""
import time
from datetime import datetime
from pathlib import Path

import pytest

from remo import briefing as B
from remo.memory import Memory


def test_plan_covers_reminders_and_notes(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_reminder("chai dekhna", time.time() + 600)
    mem.add_note("maths mein integration ho gaya")
    say = B.compose_plan(mem)
    assert "chai dekhna" in say and "integration" in say
    mem.close()


def test_plan_empty_state(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    say = B.compose_plan(mem, datetime(2026, 11, 10, 9, 0))
    assert "koi reminder nahi" in say and "kuch yaad nahi" in say
    mem.close()


@pytest.mark.parametrize("said", ["aaj ka plan batao", "today's plan", "subah ka plan"])
def test_plan_queries(said: str) -> None:
    assert B.is_plan_query(said) is True


def test_daily_schedule_setting(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    assert B.get_daily_plan_at(mem) == ""
    B.set_daily_plan_at(mem, "08:30")
    assert B.get_daily_plan_at(mem) == "08:30"
    with pytest.raises(ValueError):
        B.set_daily_plan_at(mem, "8:30am")
    mem.close()
