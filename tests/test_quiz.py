"""Quiz: blank-making, sessions, judging, stop."""
from pathlib import Path

import pytest

from remo import quiz as Q
from remo.memory import Memory


@pytest.fixture()
def mem(tmp_path: Path) -> Memory:
    m = Memory(tmp_path / "remo.db")
    m.add_note("maths mein integration ho gaya")
    m.add_note("differential equations baaki hai")
    m.add_note("photosynthesis mein sunlight zaroori hai")
    yield m
    m.close()


def test_make_blank_targets_longest_meaningful_word() -> None:
    question, answer = Q.make_blank("maths mein integration ho gaya") or ("", "")
    assert answer == "integration"
    assert "___" in question and "integration" not in question


def test_make_blank_needs_substance() -> None:
    assert Q.make_blank("haan ji") is None


def test_quiz_flow_scores_and_finales(mem: Memory) -> None:
    session, first = Q.start_quiz(mem)
    assert session is not None and first.startswith("Sawal 1:")
    session, reply, done = Q.answer_question(mem, session, session.blank)
    assert "Sahi jawab" in reply and done is False
    session, reply, done = Q.answer_question(mem, session, "bilkul galat jawab xyz")
    assert "Sahi tha" in reply
    while not done:
        session, reply, done = Q.answer_question(mem, session, "bas")
    assert "Score:" in reply


def test_quiz_needs_notes(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "empty.db")
    session, say = Q.start_quiz(mem)
    assert session is None and "notes kam" in say
    mem.close()


def test_judge_exact_and_miss() -> None:
    assert Q.judge("integration", "Integration ho gaya tha") == 1.0
    assert Q.judge("integration", "kirana se atta lao") < Q.PASS_SCORE


@pytest.mark.parametrize("said", ["bas", "ruk jao", "stop"])
def test_stop_words(said: str) -> None:
    assert Q.is_stop(said) is True


def test_session_serializes(mem: Memory) -> None:
    session, _ = Q.start_quiz(mem)
    assert session is not None
    clone = Q.QuizSession.from_dict(session.to_dict())
    assert clone == session


def test_unknown_topic_says_so(mem: Memory) -> None:
    session, say = Q.start_quiz(mem, topic="sanskrit")
    assert session is None
    assert "sanskrit" in say and "koi aur topic" in say.lower()


def test_empty_memory_asks_for_notes_first(tmp_path: Path) -> None:
    empty = Memory(tmp_path / "empty.db")
    session, say = Q.start_quiz(empty)
    assert session is None
    assert "yaad karwao" in say
    empty.close()
