"""Turn routing: save, repeat, recall, left-off, undo, help (no voice-out)."""
from pathlib import Path

import pytest

from remo import turn
from remo.lang import HI as HI_STRINGS

ACK_SAVED_HI = HI_STRINGS["ack_saved"]
from remo.config import Settings
from remo.memory import Memory


@pytest.fixture()
def mem(tmp_path: Path) -> Memory:
    m = Memory(tmp_path / "remo.db")
    yield m
    m.close()


def _settings() -> Settings:
    return Settings(gnani_api_key="test-key")


def test_save_turn_stores_and_acks(mem: Memory) -> None:
    result = turn.handle_text("yaad rakhna maths mein integration ho gaya", mem=mem, settings=_settings(), speak=False)
    assert result.action == "saved"
    assert result.text == ACK_SAVED_HI
    assert result.audio is None
    assert "integration" in mem.list_recent()[0].text


def test_bare_keyword_asks_for_repeat(mem: Memory) -> None:
    result = turn.handle_text("remember", mem=mem, settings=_settings(), speak=False)
    assert result.action == "repeat"
    assert mem.list_recent() == []


def test_left_off_turn_leads_with_pending(mem: Memory) -> None:
    mem.add_note("login fix ho gaya")
    mem.add_note("docs baaki hai")
    result = turn.handle_text("kya bacha hai?", mem=mem, settings=_settings(), speak=False)
    assert result.action == "left_off"
    assert "docs" in result.text


def test_recall_turn_reads_matches(mem: Memory) -> None:
    mem.add_note("issue 214 mein caching wala comment pending hai")
    result = turn.handle_text("issue 214 mein kya tha?", mem=mem, settings=_settings(), speak=False)
    assert result.action == "recall"
    assert "caching" in result.text


def test_unknown_statement_gets_help(mem: Memory) -> None:
    result = turn.handle_text("hello hello", mem=mem, settings=_settings(), speak=False)
    assert result.action == "help"
    assert "yaad rakhna" in result.text


def test_undo_flow_asks_then_forgets(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    mem.add_note("pehli baat")
    mem.add_note("aakhri baat")
    asked = turn.handle_text("bhool jao last wali baat", mem=mem, settings=_settings(), speak=False)
    assert asked.action == "undo_ask" and asked.pending == {"action": "undo"}
    done = turn.confirm_pending(mem, asked.pending, True, settings=_settings(), speak=False)
    assert done.action == "undone"
    assert [n.text for n in mem.list_recent()] == ["pehli baat"]
    kept = turn.confirm_pending(mem, {"action": "undo"}, False, settings=_settings(), speak=False)
    assert kept.action == "kept"


def test_forget_flow_targets_best_match(mem: Memory) -> None:
    mem.add_note("maths notes")
    mem.add_note("kirana list")
    asked = turn.handle_text("bhool jao kirana list", mem=mem, settings=_settings(), speak=False)
    assert asked.action == "forget_ask"
    done = turn.confirm_pending(mem, asked.pending, True, settings=_settings(), speak=False)
    assert done.action == "forgot"
    assert [n.text for n in mem.list_recent()] == ["maths notes"]


def test_voice_out_failure_degrades_to_text(mem: Memory, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("tts down")

    monkeypatch.setattr(turn, "synthesize", boom)
    result = turn.handle_text("yaad rakhna test note", mem=mem, settings=_settings(), speak=True)
    assert result.action == "saved" and result.text == ACK_SAVED_HI and result.audio is None
