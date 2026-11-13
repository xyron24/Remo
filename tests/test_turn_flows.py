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


def test_llm_answer_used_when_available(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    _run("yaad rakhna kal kirana se atta lena hai", mem)
    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: None)
    monkeypatch.setattr(llm_mod, "compose", lambda *a, **k: "Kal atta lena hai, kirana se.")
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("kirana se kya lena hai?", mem=mem, settings=settings, speak=False)
    assert result.action == "recall"
    assert result.text == "Kal atta lena hai, kirana se."


def test_llm_failure_falls_back_to_extractive(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    _run("yaad rakhna kal kirana se atta lena hai", mem)
    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: None)
    monkeypatch.setattr(llm_mod, "compose", lambda *a, **k: None)
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("kirana se kya lena hai?", mem=mem, settings=settings, speak=False)
    assert result.action == "recall"
    assert "Aapne kaha tha" in result.text


def test_llm_first_understands_everything(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    monkeypatch.setattr(
        llm_mod, "try_intent", lambda *a, **k: {"intent": "save", "save_text": "ye sab karna"}
    )
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("remember, ye sab karna", mem=mem, settings=settings, speak=False)
    assert result.action == "saved"
    assert "yaad rakh lunga" in result.text
    assert "ye sab karna" in mem.list_recent(1)[0].text


def test_llm_other_speaks_guarded_reply(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    monkeypatch.setattr(
        llm_mod, "try_intent", lambda *a, **k: {"intent": "other", "reply": "Namaste! Kaise ho?"}
    )
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("namaste", mem=mem, settings=settings, speak=False)
    assert result.action == "chat"
    assert result.text == "Namaste! Kaise ho?"


def test_llm_intent_none_uses_patterns(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: None)
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("yaad rakhna chai pini hai", mem=mem, settings=settings, speak=False)
    assert result.action == "saved"
    assert "Yaad kar liya" in result.text


def test_llm_forget_remind_quiz_briefing_dispatch(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    _run("yaad rakhna maths mein integration ho gaya", mem)

    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: {"intent": "forget", "target": "maths"})
    assert turn_mod.handle_text("ise hata do", mem=mem, settings=settings, speak=False).action == "forget_ask"

    monkeypatch.setattr(
        llm_mod, "try_intent",
        lambda *a, **k: {"intent": "remind", "remind_task": "chai dekhna", "remind_when": "5 minute baad"},
    )
    assert turn_mod.handle_text("chai ka dhyan rakhna", mem=mem, settings=settings, speak=False).action == "remind_confirm"

    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: {"intent": "quiz", "quiz_topic": "maths"})
    assert turn_mod.handle_text("quiz time", mem=mem, settings=settings, speak=False).action == "quiz_ask"

    monkeypatch.setattr(llm_mod, "try_intent", lambda *a, **k: {"intent": "briefing"})
    assert turn_mod.handle_text("briefing chahiye", mem=mem, settings=settings, speak=False).action == "plan"


def test_devanagari_task_question_lists_pending(mem: Memory) -> None:
    _run("yaad rakhna maths mein integration ho gaya, differential baaki hai", mem)
    result = _run("क्या टास्क बचे हैं", mem)
    assert result.action == "left_off"
    assert "differential" in result.text


def test_devanagari_welcome_and_quiz_route(mem: Memory) -> None:
    _run("yaad rakhna maths mein integration ho gaya", mem)
    assert _run("वेलकम बैक", mem).action == "welcome"
    assert _run("क्विज़ करो", mem).action == "quiz_ask"


def test_devanagari_remind_routes_to_time_question(mem: Memory) -> None:
    result = _run("कल चाय याद दिलाना", mem)
    assert "Kab yaad dilaun" in result.text


def test_wake_up_phrasing_arms_reminder(mem: Memory) -> None:
    result = _run("mujhe kal subah 9 baje utha dena", mem)
    assert result.action == "remind_confirm"
    assert "9" in result.text and "utha dena" in result.text


def test_watchlist_without_link_asks_for_it(mem: Memory) -> None:
    result = _run("koi naya repository watchlist mein daalo", mem)
    assert "link bolo" in result.text or "link" in result.text.lower()


def test_obligation_verbs_count_as_pending() -> None:
    from remo import recall as R

    assert R._PENDING_PAT.search("kal kirana se atta lena hai")
    assert R._PENDING_PAT.search("mujhe kal ghar ki safai karni hai")
    assert R._PENDING_PAT.search("demo video banana hai")
    assert R._PENDING_PAT.search("मुझे कल घर की सफाई करनी है।")
    assert not R._PENDING_PAT.search("khana taiyaar hai")
    assert not R._PENDING_PAT.search("yeh gaana hai")


def test_add_task_saves_note_and_pending_entry(mem: Memory) -> None:
    result = _run("add task buy milk tomorrow", mem)
    assert result.action == "task_added"
    assert "Task jod diya" in result.text
    assert "buy milk" in mem.list_recent(1)[0].text
    entry = mem.find_work_entry("", "")
    assert entry is not None and any("buy milk" in p for p in entry.pending)


def test_add_task_devanagari_and_empty(mem: Memory) -> None:
    result = _run("टास्क जोड़ो दूध लाना", mem)
    assert result.action == "task_added"
    assert mem.find_work_entry("", "") is not None
    assert "Kaun sa task" in _run("add task", mem).text


def test_llm_add_task_dispatch(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from remo import llm as llm_mod
    from remo import turn as turn_mod

    monkeypatch.setattr(
        llm_mod, "try_intent", lambda *a, **k: {"intent": "add_task", "task_text": "call mummy"}
    )
    settings = Settings(gnani_api_key="test-key", gemini_api_keys=("g-test",))
    result = turn_mod.handle_text("mummy ko call karna hai, yaad rakhna", mem=mem, settings=settings, speak=False)
    assert result.action == "task_added"
    assert mem.find_work_entry("", "") is not None


def test_left_off_unions_work_pending_without_dupes(mem: Memory) -> None:
    _run("yaad rakhna server deploy karna baaki hai", mem)
    mem.upsert_work_entry("student", "", "", [], ["server deploy karna baaki hai", "docs likhna hai"])
    result = _run("kya task bache hain?", mem)
    assert result.action == "left_off"
    assert "docs likhna hai" in result.text
    assert result.text.count("server deploy karna baaki hai") == 1


def test_recall_answers_each_question_from_its_own_note(mem: Memory) -> None:
    _run("yaad rakhna live server check ho gaya", mem)
    _run("yaad rakhna differential equations baaki hai", mem)
    first = _run("differential ka kya haal hai?", mem)
    assert "differential" in first.text
    assert "live server" not in first.text
    second = _run("server ka kya hua?", mem)
    assert "live server" in second.text
    assert "differential" not in second.text
