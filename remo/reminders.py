"""Reminders: Hinglish time parsing, persistent firing, spoken alarms.

Understands "5 minute baad", "saade nau", "kal subah 9 baje", "friday 4 pm".
Fired reminders disarm in SQLite, so alarms survive restarts.
"""
from __future__ import annotations

import logging
import math
import re
import struct
import threading
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

from remo.memory import Memory, Reminder

log = logging.getLogger("reminders")

NUM_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "chaar": 4, "char": 4,
    "paanch": 5, "panch": 5, "che": 6, "chhe": 6, "saat": 7,
    "aath": 8, "ath": 8, "nau": 9, "nav": 9, "das": 10,
    "gyarah": 11, "baarah": 12, "barah": 12,
}

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "somvar": 0, "somvaar": 0, "mangalvar": 1, "mangal": 1,
    "budhvar": 2, "budh": 2, "guruwar": 3, "brihaspati": 3,
    "shukravar": 4, "shukra": 4, "shanivar": 5, "shani": 5,
    "ravivaar": 6, "ravivar": 6,
}

FILLERS = {
    "yaad", "dilana", "dila", "dena", "remind", "me", "reminder",
    "mujhe", "ko", "ki", "ke", "ka", "please", "zara", "ek", "baje",
    "tu", "tum", "aap",
}

_RELATIVE = re.compile(
    r"(\d+)\s*(seconds?|minutes?|mins?|ghante?|ghanta|hours?|hrs?|din|dino|hafte|hafto)\s*baad", re.I
)

_RELATIVE_SECONDS = (
    (("hour", "hr", "ghant", "ghanta"), 3600),
    (("min",), 60),
    (("din", "dino"), 86400),
    (("haft", "hafto"), 604800),
)
_FRACTION = re.compile(r"(sava|saade|saadhe|sadhe|paune|pauna)\s*(\d+|[a-zA-Z]+)", re.I)
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)?", re.I)
_MERIDIEM = re.compile(r"(\d{1,2}|[a-zA-Z]+)\s*(am|pm)\b", re.I)
_BAJE = re.compile(r"(subah|dopahar|shaam|raat)?\s*(\d+|[a-zA-Z]+)\s*baje\s*(am|pm)?", re.I)
_BAJE_TRAIL = re.compile(r"(\d+)\s*baje\s*(subah|dopahar|shaam|raat)", re.I)


def _num(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return NUM_WORDS.get(token)


def _daypart_hour(hour: int, part: str) -> int:
    if part == "subah":
        return hour
    if part == "dopahar":
        return hour if hour >= 10 else hour + 12
    if part == "shaam":
        return hour if hour >= 12 else hour + 12
    if part == "raat":
        if hour == 12:
            return 0
        return hour + 12 if 6 <= hour <= 11 else hour
    return hour


def _tod_candidates(hour: int, minute: int, base: datetime, now: datetime) -> datetime | None:
    hours = [hour] if hour >= 12 else [hour, hour + 12]
    for extra in range(0, 3):
        for candidate in hours:
            moment = (base + timedelta(days=extra)).replace(
                hour=candidate % 24, minute=minute, second=0, microsecond=0
            )
            if moment > now:
                return moment
    return None


def _extract(text: str, now: datetime) -> tuple[list[tuple[int, int]], datetime | None]:
    """Matched time spans + resolved datetime (None when no time found)."""
    spans: list[tuple[int, int]] = []

    match = _RELATIVE.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        scale = 1
        for prefixes, seconds in _RELATIVE_SECONDS:
            if unit.startswith(prefixes):
                scale = seconds
                break
        return [(match.start(), match.end())], now + timedelta(seconds=amount * scale)

    offset = 0
    weekday = False
    match = re.search(r"\bparso\b", text, re.I)
    if match:
        offset, spans = 2, [(match.start(), match.end())]
    else:
        for name, day in WEEKDAYS.items():
            match = re.search(rf"\b{name}\b", text, re.I)
            if match:
                offset = (day - now.weekday()) % 7
                weekday = True
                spans = [(match.start(), match.end())]
                break
        else:
            match = re.search(r"\bkal\b", text, re.I)
            if match:
                offset, spans = 1, [(match.start(), match.end())]
            else:
                match = re.search(r"\baaj\b", text, re.I)
                if match:
                    spans = [(match.start(), match.end())]

    hour: int | None = None
    minute = 0
    explicit = False

    match = _FRACTION.search(text)
    if match and _num(match.group(2)) is not None:
        base = _num(match.group(2) or "") or 0
        kind = match.group(1).lower()
        if kind.startswith("sava"):
            hour, minute = base, 15
        elif kind.startswith("paun"):
            hour, minute = base - 1, 45
        else:
            hour, minute = base, 30
        spans.append((match.start(), match.end()))
    else:
        match = _CLOCK.search(text)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            meridiem = (match.group(3) or "").lower()
            if meridiem == "am":
                hour, explicit = hour % 12, True
            elif meridiem == "pm":
                hour, explicit = hour % 12 + 12, True
            spans.append((match.start(), match.end()))
        else:
            match = next(
                (m for m in _MERIDIEM.finditer(text) if _num(m.group(1)) is not None), None
            )
            if match:
                num = _num(match.group(1) or "") or 0
                if match.group(2).lower() == "am":
                    hour, explicit = num % 12, True
                else:
                    hour, explicit = num % 12 + 12, True
                spans.append((match.start(), match.end()))
            trail = _BAJE_TRAIL.search(text) if hour is None else None
            if hour is None:
                match = next(
                    (m for m in _BAJE.finditer(text) if _num(m.group(2)) is not None), None
                )
            if trail:
                hour = int(trail.group(1))
                hour = _daypart_hour(hour, trail.group(2).lower())
                explicit = True
                spans.append((trail.start(), trail.end()))
            elif match and _num(match.group(2)) is not None:
                hour = _num(match.group(2) or "") or 0
                part = (match.group(1) or "").lower()
                meridiem = (match.group(3) or "").lower()
                if meridiem == "am":
                    hour, explicit = hour % 12, True
                elif meridiem == "pm":
                    hour, explicit = hour % 12 + 12, True
                elif part:
                    hour, explicit = _daypart_hour(hour, part), True
                spans.append((match.start(), match.end()))

    if hour is None or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return spans, None

    base = now + timedelta(days=offset)
    if explicit:
        moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= now:
            moment += timedelta(days=7 if weekday else 1)
        return spans, moment
    if weekday:
        for extra in (0, 7):
            for candidate in [hour] if hour >= 12 else [hour, hour + 12]:
                moment = (base + timedelta(days=extra)).replace(
                    hour=candidate % 24, minute=minute, second=0, microsecond=0
                )
                if moment > now:
                    return spans, moment
        return spans, None
    return spans, _tod_candidates(hour, minute, base, now)


def parse_reminder_time(text: str, now: datetime | None = None) -> datetime | None:
    """Resolve the reminder moment, or None when no time is found."""
    return _extract(text, now or datetime.now())[1]


def extract_time_mention(text: str, now: datetime | None = None) -> tuple[str, datetime | None]:
    """The time words as said ("2 din baad") plus the resolved moment, if any."""
    now = now or datetime.now()
    spans, moment = _extract(text, now)
    if moment is None:
        return "", None
    mention = " ".join(text[start:end] for start, end in spans).strip()
    return mention, moment


def split_task_time(text: str, now: datetime | None = None) -> tuple[str, datetime | None]:
    """Split "kal 9 baje chai yaad dilana" into ("chai", datetime)."""
    now = now or datetime.now()
    spans, moment = _extract(text, now)
    kept = "".join(
        ch for i, ch in enumerate(text) if not any(s <= i < e for s, e in spans)
    )
    words = [w for w in re.split(r"\s+", kept.strip()) if w.lower().strip(".,!?;:") not in FILLERS]
    task = re.sub(r"\s+", " ", " ".join(words)).strip(" .,!?;:")
    return task, moment


def format_readback(moment: datetime, now: datetime | None = None) -> str:
    """"kal subah 9 baje" style read-back for confirmation."""
    now = now or datetime.now()
    delta_days = (moment.date() - now.date()).days
    if delta_days <= 0:
        day = "aaj"
    elif delta_days == 1:
        day = "kal"
    elif delta_days < 7:
        day = moment.strftime("%A")
    else:
        day = moment.strftime("%d %b")
    hour = moment.hour
    part = "subah" if 4 <= hour < 12 else "dopahar" if 12 <= hour < 16 else "shaam" if 16 <= hour < 20 else "raat"
    twelve = hour % 12 or 12
    hm = f"{twelve} baje" if moment.minute == 0 else f"{twelve}:{moment.minute:02d}"
    return f"{day} {part} {hm}"


def collect_due(db_path: str | Path) -> list[Reminder]:
    """Pop all due armed reminders (fresh connection per call: thread-safe)."""
    mem = Memory(db_path)
    try:
        due = mem.list_armed(time.time())
        for reminder in due:
            mem.disarm(reminder.id)
        return due
    finally:
        mem.close()


class ReminderScheduler(threading.Thread):
    """Daemon loop: fires due reminders through a callback. Survives restarts."""

    def __init__(self, db_path: str | Path, callback, interval: float = 10.0) -> None:
        super().__init__(daemon=True)
        self.db_path = str(db_path)
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()

    def tick(self) -> None:
        for reminder in collect_due(self.db_path):
            try:
                self.callback(reminder)
            except Exception as exc:  # noqa: BLE001 - one bad alarm must not stop the loop
                log.warning("reminder callback failed: %s", exc)

    def run(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval):
            self.tick()

    def stop(self) -> None:
        self._stop.set()


def chime_wav(path: str | Path, freq: float = 880.0, ms: int = 400, rate: int = 16000) -> Path:
    """Generate a soft alarm chime (sine with decay) — no TTS cost."""
    path = Path(path)
    frames = int(rate * ms / 1000)
    samples = [
        int(12000 * math.sin(2 * math.pi * freq * i / rate) * (1 - i / frames)) for i in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path
