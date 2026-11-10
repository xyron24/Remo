"""Recall: hybrid ranking, classifiers, pending-first composition."""
from pathlib import Path

import pytest

from remo import recall as R
from remo.memory import Memory


@pytest.fixture()
def mem(tmp_path: Path) -> Memory:
    m = Memory(tmp_path / "remo.db")
    m.add_note("maths mein integration ho gaya")
    m.add_note("differential equations baaki hai")
    m.add_note("kirana se atta lena hai")
    yield m
    m.close()


def test_hybrid_search_prefers_keyword_match(mem: Memory) -> None:
    hits = R.hybrid_search(mem, "differential", limit=3)
    assert hits and "differential" in hits[0].text


def test_hybrid_search_finds_meaning_overlap(mem: Memory) -> None:
    hits = R.hybrid_search(mem, "integration maths", limit=3)
    assert hits and "integration" in hits[0].text


@pytest.mark.parametrize(
    "said",
    [
        "maths mein kya bacha hai?",
        "kya baaki hai?",
        "where did i leave off",
        "what is left in issue 214",
    ],
)
def test_left_off_classifier(said: str) -> None:
    assert R.is_left_off_query(said) is True


@pytest.mark.parametrize("said", ["kal kya kaha tha?", "tum kaun ho", "issue 214 batao"])
def test_recall_classifier(said: str) -> None:
    assert R.is_recall_query(said) is True
    assert R.is_left_off_query(said) is False


def test_left_off_is_pending_first(mem: Memory) -> None:
    say = R.compose_left_off(mem.list_recent(20))
    assert "baaki hai" in say
    assert say.index("differential") < say.index("purani baatein")


def test_left_off_empty_memory(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "empty.db")
    assert "kuch yaad nahi" in R.compose_left_off([])
    mem.close()


def test_recall_compose_with_and_without_hits(mem: Memory) -> None:
    assert "differential" in R.compose_recall(R.hybrid_search(mem, "differential"))
    assert "yaad nahi" in R.compose_recall([])


def test_answer_states_said_due_and_reminder(tmp_path: Path) -> None:
    import time as _time

    mem = Memory(tmp_path / "remo.db")
    mem.add_note("project ka UI weak hai, 2 din baad update karna hai")
    note = mem.list_recent()[0]
    mem.add_reminder("UI update", _time.time() + 2 * 86400 - 60)
    say = R.compose_answer([note], mem)
    assert "Aapne kaha tha" in say and "2 din baad" in say and "reminder laga diya" in say
    mem.close()


def test_answer_without_time_or_reminder(mem: Memory) -> None:
    hits = R.hybrid_search(mem, "kirana")
    say = R.compose_answer(hits, mem)
    assert "Aapne kaha tha" in say and "atta" in say
    assert R.compose_answer([], mem) == R.compose_recall([])
