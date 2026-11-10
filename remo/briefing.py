"""Day's plan: today's reminders plus recent notes, spoken or scheduled."""
from __future__ import annotations

from datetime import datetime

from remo.brain_keywords import normalize
from remo.memory import Memory

PLAN_MARKERS = (
    "aaj ka plan",
    "aajki plan",
    "subah ka plan",
    "today's plan",
    "todays plan",
    "today plan",
    "day plan",
    "morning briefing",
    "din ka plan",
)

DAILY_PLAN_KEY = "daily_plan_at"


def is_plan_query(text: str) -> bool:
    norm = normalize(text)
    return any(marker in norm for marker in PLAN_MARKERS)


def _clock(moment: datetime) -> str:
    """12-hour clock without platform-specific strftime flags."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def compose_plan(mem: Memory, now: datetime | None = None) -> str:
    """Plain-template plan: always works, with or without a reasoning model."""
    now = now or datetime.now()
    today = [r for r in mem.list_armed() if datetime.fromtimestamp(r.fire_at).date() == now.date()]
    notes = mem.list_recent(5)
    parts: list[str] = []
    if today:
        items = "; ".join(
            f"{r.text} ({_clock(datetime.fromtimestamp(r.fire_at))})" for r in today[:5]
        )
        parts.append(f"Aaj ke liye {len(today)} reminders: {items}.")
    else:
        parts.append("Aaj ke liye koi reminder nahi hai.")
    if notes:
        items = "; ".join(n.text for n in notes[:3])
        parts.append(f"Aakhri baatein: {items}.")
    else:
        parts.append("Abhi kuch yaad nahi karwaya.")
    return " ".join(parts)


def get_daily_plan_at(mem: Memory) -> str:
    return mem.get_setting(DAILY_PLAN_KEY, "")


def set_daily_plan_at(mem: Memory, hh_mm: str) -> None:
    datetime.strptime(hh_mm, "%H:%M")  # validates; raises ValueError when bad
    mem.set_setting(DAILY_PLAN_KEY, hh_mm)
