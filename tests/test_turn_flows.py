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
    assert session.note_ids and session.total == 1  # only the maths note is on-topic
    answered = turn.answer_quiz(mem, asked.pending, session.blank, settings=_settings(), speak=False)
    assert "Sahi jawab" in answered.text
    assert answered.action == "quiz_done" and "Score: 1/1" in answered.text
    assert answered.pending is None


def test_devanagari_remember_saves_end_to_end(mem: Memory) -> None:
    result = _run("रिमेम्बर मुझे कल नये प्रोजेक्ट पर काम करना है", mem)
    assert result.action == "saved"
    assert "Yaad kar liya" in result.text
    assert "नये प्रोजेक्ट" in mem.list_recent(1)[0].text


def test_tomorrow_plan_answers_directly(mem: Memory) -> None:
    _run("yaad rakhna kal kirana se atta aur dal lena hai", mem)
    _run("yaad rakhna mujhe kal ghar ki safai karni hai", mem)
    result = _run("kal ka plan kya hai", mem)
    assert result.action == "plan"
    assert "Kal ke liye 2 kaam hain" in result.text
    assert "atta" in result.text and "safai" in result.text
    assert "Aapne kaha tha" not in result.text


def test_tomorrow_left_off_lists_day_directly(mem: Memory) -> None:
    _run("yaad rakhna mujhe kal 2 PR merge karne hain", mem)
    _run("yaad rakhna kal kirana se atta aur dal lena hai", mem)
    result = _run("kal kya bacha hai?", mem)
    assert result.action == "plan"
    assert "Kal ke liye 2 kaam hain" in result.text
    assert "Aapne kaha tha" not in result.text and "Mujhe ye mila" not in result.text
    past = _run("kal kya kaha tha?", mem)
    assert past.action == "recall"


def test_recall_answers_each_question_from_its_own_note(mem: Memory) -> None:
    _run("yaad rakhna live server check ho gaya", mem)
    _run("yaad rakhna differential equations baaki hai", mem)
    first = _run("differential ka kya haal hai?", mem)
    assert "differential" in first.text
    assert "live server" not in first.text
    second = _run("server ka kya hua?", mem)
    assert "live server" in second.text
    assert "differential" not in second.text
