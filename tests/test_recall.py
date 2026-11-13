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


@pytest.mark.parametrize(
    "said",
    [
        "kya task bache hain?",
        "kya kaam bacha hai?",
        "kaun se task bache hain?",
        "show my tasks",
        "क्या टास्क बचे हैं",
        "क्या बचा है",
        "कौन से टास्क बचे हैं",
        "क्या काम बचा है",
    ],
)
def test_left_off_classifier_tasks_and_devanagari(said: str) -> None:
    assert R.is_left_off_query(said) is True


@pytest.mark.parametrize(
    "said",
    [
        "differential ka kya haal hai?",
        "server ka kya hua?",
        "kal kya kaha tha?",
    ],
)
def test_left_off_rejects_state_and_past_questions(said: str) -> None:
    assert R.is_left_off_query(said) is False


@pytest.mark.parametrize("said", ["kal kya kaha tha?", "tum kaun ho", "issue 214 batao"])
def test_recall_classifier(said: str) -> None:
    assert R.is_recall_query(said) is True
    assert R.is_left_off_query(said) is False


@pytest.mark.parametrize("said", ["क्या हाल है?", "कल क्या कहा था?", "तुम कौन हो"])
def test_recall_classifier_devanagari(said: str) -> None:
    assert R.is_recall_query(said) is True


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


def test_unrelated_query_returns_no_hits(mem: Memory) -> None:
    assert R.hybrid_search(mem, "sahara desert camel safari") == []


def test_long_note_does_not_shadow_relevant_short_note(tmp_path: Path) -> None:
    m = Memory(tmp_path / "remo.db")
    m.add_note(
        "maine jo abhi project banaya hai uska UI bahut weak hai, mujhe use update karna hai"
        " lekin main 2 din baad karunga, bahut saara vistaar se varnan taaki ye note lamba lage"
    )
    m.add_note("differential equations baaki hai")
    hits = R.hybrid_search(m, "differential ka kya haal hai?")
    assert hits and "differential" in hits[0].text
    assert all("project" not in h.text for h in hits[:1])
    m.close()


def test_tell_all_lists_recent_notes(mem: Memory) -> None:
    assert R.is_tell_all_query("kya yaad hai?") is True
    assert R.is_tell_all_query("differential ka kya haal hai?") is False
    say = R.compose_recall(mem.list_recent(3))
    assert "Mujhe ye mila" in say


def test_latin_query_finds_devanagari_note(tmp_path: Path) -> None:
    m = Memory(tmp_path / "remo.db")
    m.add_note("मुझे कल घर की सफाई करनी है।")
    m.add_note("live server check ho gaya")
    hits = R.hybrid_search(m, "kal ghar ki safai krni hai?")
    assert hits and "सफाई" in hits[0].text
    hits = R.hybrid_search(m, "mujhe kal kya krna hai")
    assert hits and "सफाई" in hits[0].text
    m.close()


def test_karne_counts_as_pending(tmp_path: Path) -> None:
    m = Memory(tmp_path / "remo.db")
    m.add_note("mujhe kal 2 PR merge karne hain")
    say = R.compose_answer(m.list_recent(1), m)
    assert "baaki hai" in say
    assert "Mujhe ye mila" not in say
    m.close()


def test_devanagari_pending_note_composes_pending_tail(tmp_path: Path) -> None:
    m = Memory(tmp_path / "remo.db")
    m.add_note("मुझे कल नये प्रोजेक्ट पर काम करना है")
    say = R.compose_answer(m.list_recent(1), m)
    assert "baaki hai" in say
    assert "Mujhe ye mila" not in say
    m.close()
