"""Reminder times: Hinglish parsing, task split, firing, chime."""
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

from remo.memory import Memory
from remo.reminders import (
    ReminderScheduler,
    chime_wav,
    collect_due,
    format_readback,
    parse_reminder_time,
    split_task_time,
)

TUESDAY_9AM = datetime(2026, 11, 10, 9, 0, 0)


def test_relative_times() -> None:
    assert parse_reminder_time("5 minute baad chai dekhna", TUESDAY_9AM) == TUESDAY_9AM + timedelta(minutes=5)
    assert parse_reminder_time("2 ghante baad call karna", TUESDAY_9AM) == TUESDAY_9AM + timedelta(hours=2)


def test_named_days() -> None:
    assert parse_reminder_time("kal subah 9 baje meeting", TUESDAY_9AM) == datetime(2026, 11, 11, 9, 0)
    assert parse_reminder_time("parso 10 baje dawa", TUESDAY_9AM) == datetime(2026, 11, 12, 10, 0)


def test_fractions() -> None:
    assert parse_reminder_time("sava nau baje chai", TUESDAY_9AM) == datetime(2026, 11, 10, 9, 15)
    assert parse_reminder_time("saade paanch baje walk", TUESDAY_9AM) == datetime(2026, 11, 10, 17, 30)
    assert parse_reminder_time("paune aath baje class", TUESDAY_9AM) == datetime(2026, 11, 10, 19, 45)


def test_weekday_and_clock() -> None:
    friday = TUESDAY_9AM + timedelta(days=(4 - TUESDAY_9AM.weekday()) % 7)
    assert parse_reminder_time("friday 4 pm meeting hai", TUESDAY_9AM) == friday.replace(hour=16, minute=0)
    assert parse_reminder_time("1:10 baje lunch", TUESDAY_9AM) == datetime(2026, 11, 10, 13, 10)


def test_dayparts() -> None:
    assert parse_reminder_time("shaam 5 baje walk", TUESDAY_9AM) == datetime(2026, 11, 10, 17, 0)
    assert parse_reminder_time("9 baje raat dawa", TUESDAY_9AM) == datetime(2026, 11, 10, 21, 0)


def test_task_split() -> None:
    task, moment = split_task_time("kal subah 9 baje Go assignment yaad dilana", TUESDAY_9AM)
    assert task == "Go assignment"
    assert moment == datetime(2026, 11, 11, 9, 0)
    task, moment = split_task_time("5 minute baad chai dekhna", TUESDAY_9AM)
    assert task == "chai dekhna"
    assert moment == TUESDAY_9AM + timedelta(minutes=5)


def test_no_time_found() -> None:
    assert parse_reminder_time("kabhi chai peena", TUESDAY_9AM) is None


def test_readback_words() -> None:
    assert format_readback(datetime(2026, 11, 11, 9, 0), TUESDAY_9AM) == "kal subah 9 baje"
    assert "aaj" in format_readback(datetime(2026, 11, 10, 17, 30), TUESDAY_9AM)


def test_due_collection_disarms(tmp_path: Path) -> None:
    db = tmp_path / "remo.db"
    mem = Memory(db)
    mem.add_reminder("abhi wala", time.time() - 1)
    mem.add_reminder("baad wala", time.time() + 3600)
    mem.close()
    due = collect_due(db)
    assert [r.text for r in due] == ["abhi wala"]
    assert collect_due(db) == []


def test_scheduler_fires_and_stops(tmp_path: Path) -> None:
    db = tmp_path / "remo.db"
    mem = Memory(db)
    mem.add_reminder("alarm bajao", time.time() - 1)
    mem.close()
    fired: list = []
    sched = ReminderScheduler(db, fired.append, interval=60)
    sched.start()
    time.sleep(0.3)
    sched.stop()
    sched.join(timeout=5)
    assert [r.text for r in fired] == ["alarm bajao"]


def test_chime_is_valid_wav(tmp_path: Path) -> None:
    out = chime_wav(tmp_path / "chime.wav")
    with wave.open(str(out), "rb") as wav:
        assert wav.getnframes() > 1000 and wav.getframerate() == 16000
