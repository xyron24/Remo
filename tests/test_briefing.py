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


@pytest.mark.parametrize(
    "said", ["aaj ka plan batao", "today's plan", "subah ka plan", "आज का प्लान बताओ"]
)
def test_plan_queries(said: str) -> None:
    assert B.is_plan_query(said) is True


@pytest.mark.parametrize("said", ["kal ka plan kya hai", "tomorrow's plan?", "कल का प्लान क्या है"])
def test_tomorrow_plan_queries(said: str) -> None:
    assert B.is_plan_query(said) is True
    assert B.plan_day(said) == "tomorrow"


@pytest.mark.parametrize("said", ["aaj ka plan batao", "today's plan", "mera plan batao"])
def test_today_and_bare_plan_have_no_day(said: str) -> None:
    assert B.is_plan_query(said) is True
    assert B.plan_day(said) is None


def test_tomorrow_plan_lists_every_item_directly(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("kal kirana se atta aur dal lena hai")
    mem.add_note("मुझे कल घर की सफाई करनी है।")
    mem.add_note("live server check ho gaya")
    say = B.compose_day_plan(mem, "tomorrow")
    assert "Kal ke liye 2 kaam hain" in say
    assert "atta" in say and "सफाई" in say
    assert "live server" not in say
    assert "Aapne kaha tha" not in say and "Mujhe ye mila" not in say
    mem.close()


def test_tomorrow_plan_empty_state(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("live server check ho gaya")
    assert "khaas nahi" in B.compose_day_plan(mem, "tomorrow")
    mem.close()


@pytest.mark.parametrize(
    ("said", "day"),
    [
        ("kal kya bacha hai?", "tomorrow"),
        ("kal kya karna hai mujhe", "tomorrow"),
        ("parso ka kya scene hai", "dayafter"),
        ("differential ka kya haal hai?", None),
        ("kal kya kaha tha?", None),
        ("kal kya hua tha?", None),
    ],
)
def test_day_plan_routing(said: str, day: str | None) -> None:
    assert B.wants_day_plan(said) == day


def test_daily_schedule_setting(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    assert B.get_daily_plan_at(mem) == ""
    B.set_daily_plan_at(mem, "08:30")
    assert B.get_daily_plan_at(mem) == "08:30"
    with pytest.raises(ValueError):
        B.set_daily_plan_at(mem, "8:30am")
    mem.close()
