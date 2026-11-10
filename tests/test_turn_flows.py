"""Turn flows: reminders, plan, quiz through handle_text + pendings."""
from pathlib import Path

import pytest

from remo import turn
from remo.config import Settings
from remo.memory import Memory


@pytest.fixture()
def mem(tmp_path: Path) -> Memory:
    m = Memory(tmp_path / "remo.db")
    yield m
    m.close()


def _settings() -> Settings:
    return Settings(gnani_api_key="test-key")


def _run(text: str, mem: Memory):
    return turn.handle_text(text, mem=mem, settings=_settings(), speak=False)


def test_remind_flow_confirms_then_arms(mem: Memory) -> None:
    asked = _run("5 minute baad chai dekhna yaad dilana", mem)
    assert asked.action == "remind_confirm"
    assert "chai dekhna" in asked.text
    assert asked.pending and asked.pending["action"] == "remind"
    done = turn.confirm_pending_text(mem, asked.pending, "haan", settings=_settings(), speak=False)
    assert done is not None and done.action == "reminded"
    assert [r.text for r in mem.list_armed()] == ["chai dekhna"]


def test_remind_decline_arms_nothing(mem: Memory) -> None:
    asked = _run("5 minute baad chai yaad dilana", mem)
    done = turn.confirm_pending_text(mem, asked.pending, "nahi", settings=_settings(), speak=False)
    assert done is not None and done.action == "kept"
    assert mem.list_armed() == []


def test_remind_unclear_yes_no_returns_none(mem: Memory) -> None:
    asked = _run("5 minute baad chai yaad dilana", mem)
    assert turn.confirm_pending_text(mem, asked.pending, "pata nahi", settings=_settings(), speak=False) is None


def test_remind_without_time_asks_when(mem: Memory) -> None:
    result = _run("kabhi chai peena yaad dilana", mem)
    assert "Kab yaad dilaun" in result.text


def test_remind_without_task_asks_what_then_arms(mem: Memory) -> None:
    asked = _run("5 minute baad yaad dilana", mem)
    assert asked.action == "remind_ask"
    done = turn.complete_remind_task(mem, asked.pending, "chai dekhna", settings=_settings(), speak=False)
    assert done.action == "reminded"
    assert [r.text for r in mem.list_armed()] == ["chai dekhna"]


def test_plan_flow(mem: Memory) -> None:
    mem.add_note("maths mein integration ho gaya")
    result = _run("aaj ka plan batao", mem)
    assert result.action == "plan"
    assert "integration" in result.text


def test_quiz_flow_start_answer_finish(mem: Memory) -> None:
    mem.add_note("maths mein integration ho gaya")
    mem.add_note("differential equations baaki hai")
    mem.add_note("photosynthesis mein sunlight zaroori hai")
    asked = _run("maths mein quiz karo", mem)
    assert asked.action == "quiz_ask"
    from remo import quiz as quiz_mod

    session = quiz_mod.QuizSession.from_dict((asked.pending or {}).get("session", {}))
    answered = turn.answer_quiz(mem, asked.pending, session.blank, settings=_settings(), speak=False)
    assert "Sahi jawab" in answered.text
    finished = turn.answer_quiz(mem, answered.pending, "bas", settings=_settings(), speak=False)
    assert finished.action == "quiz_done" and "Score:" in finished.text
