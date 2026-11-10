"""Day's plan: today's reminders plus recent notes, spoken or scheduled."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from remo import lang as lang_mod
from remo import recall as recall_mod
from remo.brain_keywords import normalize
from remo.memory import Memory, content_tokens

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

_PLAN_WORD = re.compile(r"\bplans?\b|\bplanning\b|\bschedules?\b|प्लान|प्लॅन", re.IGNORECASE)

_DAY_WORDS = {
    "tomorrow": ("kal", "कल", "tomorrow", "udya", "उद्या"),
    "dayafter": ("parso", "परसो", "parva", "परवा"),
}

# "What was in the plan" asks about a note's contents, so it stays on recall.
_CONTENT_QUESTION = (
    "mein kya", "me kya", "में क्या", "kya tha", "kya thi", "kya the",
    "madhye kay", "मधे काय", "kay hota",
)

_DONE_PAT = re.compile(
    r"\bho ga(?:ya|yi|ye)\b|\bhogaya\b|\bho chuka\b|\bkar liya\b|\bkar diya\b"
    r"|\bdone\b|\bcompleted\b|\bfinished\b"
    r"|हो गया|हो गई|हो गए|हो चुका|कर लिया|कर दिया|पूरा|पूर्ण",
    re.IGNORECASE,
)

DAY_OFFSET = {"today": 0, "tomorrow": 1, "dayafter": 2}

DAY_TOKENS = {
    "today": {"aaj"},
    "tomorrow": {"kal", "udya"},
    "dayafter": {"parso", "parva"},
}

DAILY_PLAN_KEY = "daily_plan_at"


def _has_word(norm: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", norm) is not None


def plan_day(text: str) -> str | None:
    """'tomorrow'/'dayafter' when a plan query names a coming day, else None.

    Today and bare 'my plan' stay None: they keep the classic briefing rather
    than a day-word filtered list.
    """
    norm = normalize(text)
    if _PLAN_WORD.search(norm) is None:
        return None
    for day, words in _DAY_WORDS.items():
        if any(_has_word(norm, word) for word in words):
            return day
    return None


def is_plan_query(text: str) -> bool:
    norm = normalize(text)
    if any(marker in norm for marker in PLAN_MARKERS):
        return True
    if _PLAN_WORD.search(norm) is None:
        return False
    if plan_day(text) is not None:
        return True
    return not any(marker in norm for marker in _CONTENT_QUESTION)


# Past-tense "what did I say/do" stays on recall even with a day-word ("kal"
# also means yesterday); anything else naming a coming day lists that day.
_PAST_RECALL = (
    "kaha tha", "bola tha", "hua tha", "hui thi", "hue the",
    "kiya tha", "ki thi", "kiye the", "kya hua", "yesterday",
    "कहा था", "बोला था", "हुआ था", "हुई थी", "किया था", "क्या हुआ",
)


def wants_day_plan(text: str) -> str | None:
    """'tomorrow'/'dayafter' when asking what is left for a coming day."""
    norm = normalize(text)
    if any(marker in norm for marker in _PAST_RECALL):
        return None
    for day, words in _DAY_WORDS.items():
        if any(_has_word(norm, word) for word in words):
            return day
    return None


def _clock(moment: datetime) -> str:
    """12-hour clock without platform-specific strftime flags."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def compose_plan(mem: Memory, now: datetime | None = None, s: dict | None = None) -> str:
    """Plain-template plan: always works, with or without a reasoning model."""
    s = s or lang_mod.HI
    now = now or datetime.now()
    today = [r for r in mem.list_armed() if datetime.fromtimestamp(r.fire_at).date() == now.date()]
    notes = mem.list_recent(5)
    parts: list[str] = []
    if today:
        items = "; ".join(
            f"{r.text} ({_clock(datetime.fromtimestamp(r.fire_at))})" for r in today[:5]
        )
        parts.append(s["plan_rems"].format(n=len(today), items=items))
    else:
        parts.append(s["plan_no_rems"])
    if notes:
        items = "; ".join(n.text for n in notes[:3])
        parts.append(s["plan_notes"].format(items=items))
    else:
        parts.append(s["plan_no_notes"])
    return " ".join(parts)


def compose_day_plan(
    mem: Memory, day: str, now: datetime | None = None, s: dict | None = None, limit: int = 4
) -> str:
    """Direct day plan: every note naming that day plus reminders due on it.

    Done notes ("ho gaya") are skipped: a plan lists what is left to do, and
    "kal" plus a done verb usually means yesterday anyway.
    """
    s = s or lang_mod.HI
    now = now or datetime.now()
    target = (now + timedelta(days=DAY_OFFSET[day])).date()
    due = [r for r in mem.list_armed() if datetime.fromtimestamp(r.fire_at).date() == target]
    toks = DAY_TOKENS[day]
    notes = [
        n
        for n in mem.list_recent(50)
        if toks & set(content_tokens(f"{n.text} {n.text_latin}"))
        and not _DONE_PAT.search(f"{n.text} {n.text_latin}")
    ]
    items = [recall_mod.task_core(n.text) for n in notes]
    items += [f"{r.text} ({_clock(datetime.fromtimestamp(r.fire_at))})" for r in due]
    if not items:
        return s[f"dayplan_none_{day}"]
    verb = s["dayplan_verb_one"] if len(items) == 1 else s["dayplan_verb_many"]
    shown = "; ".join(items[:limit])
    extra = s["updates_extra"].format(n=len(items) - limit) if len(items) > limit else ""
    return s[f"dayplan_head_{day}"].format(n=len(items), verb=verb, items=shown) + extra


def get_daily_plan_at(mem: Memory) -> str:
    return mem.get_setting(DAILY_PLAN_KEY, "")


def set_daily_plan_at(mem: Memory, hh_mm: str) -> None:
    datetime.strptime(hh_mm, "%H:%M")  # validates; raises ValueError when bad
    mem.set_setting(DAILY_PLAN_KEY, hh_mm)
