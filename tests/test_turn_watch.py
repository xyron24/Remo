"""Turn flows: work entries, watching, update checks, welcome-back."""
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


def test_work_update_saves_note_and_entry(mem: Memory) -> None:
    result = _run("yaad rakhna GSoC update org Mifos issue 214: login fix ho gaya, docs baaki hai", mem)
    assert "kaam ki list" in result.text
    assert mem.find_work_entry("Mifos", "214") is not None
    assert "login fix" in mem.list_recent()[0].text


def test_left_off_with_ref_reads_entry(mem: Memory) -> None:
    _run("yaad rakhna issue 214: login fix ho gaya, docs baaki hai", mem)
    result = _run("issue 214 mein kya bacha hai?", mem)
    assert result.action == "left_off"
    assert "docs" in result.text and "Ho gaya" in result.text


def test_left_off_unknown_ref_says_so(mem: Memory) -> None:
    result = _run("issue 999 mein kya bacha hai?", mem)
    assert "koi record nahi" in result.text


def test_watch_flow_stores_url(mem: Memory) -> None:
    result = _run("watch karo https://github.com/o/r/issues/214", mem)
    assert result.action == "watching"
    assert [w.url for w in mem.list_watched()] == ["https://github.com/o/r/issues/214"]


def test_watch_bad_url_gets_help(mem: Memory) -> None:
    result = _run("watch karo ye wala", mem)
    assert "link samajh nahi" in result.text
    assert mem.list_watched() == []


def test_updates_with_nothing_watched(mem: Memory) -> None:
    result = _run("koi update aaya?", mem)
    assert "kuch watch nahi" in result.text


def test_updates_poll_and_brief_with_links(mem: Memory) -> None:
    from remo import watcher as watcher_mod

    mem.watch_url("github_issue", "https://github.com/o/r/issues/214")

    def fake_poll_all(mem_inner, token="", fetch=None, lang="hi"):
        watched = mem_inner.list_watched()[0]
        mem_inner.store_changes(watched.id, [
            ("Naya comment aaya.", "LGTM", "https://x/c1", 1.0),
            ("Issue band hua.", "", "https://x/i", 2.0),
        ])
        return watcher_mod.PollReport(checked=1, new_changes=2, checked_at=1730000000.0)

    import time
    from unittest import mock

    with mock.patch.object(watcher_mod, "poll_all", fake_poll_all):
        result = _run("koi update aaya?", mem)
    assert result.action == "updates"
    assert "2 badlaav" in result.text and "as of" in result.text
    assert result.links == ["https://x/c1", "https://x/i"]
    assert mem.unbriefed_changes() == [], "briefed once, never repeated"


def test_updates_degrade_honestly_on_errors(mem: Memory) -> None:
    from remo import watcher as watcher_mod
    from unittest import mock

    mem.watch_url("github_issue", "https://github.com/o/r/issues/214")

    def failing_poll(mem_inner, token="", fetch=None, lang="hi"):
        return watcher_mod.PollReport(checked=1, errors=["offline"], checked_at=1730000000.0)

    with mock.patch.object(watcher_mod, "poll_all", failing_poll):
        result = _run("koi update?", mem)
    assert "sampark nahi" in result.text


def test_welcome_back_combines_pending_and_deltas(mem: Memory) -> None:
    _run("yaad rakhna issue 214: docs baaki hai", mem)
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/214")
    mem.store_changes(watched.id, [("Naya comment.", "q", "https://x/1", 1.0)])
    result = _run("welcome back", mem)
    assert result.action == "welcome"
    assert "docs" in result.text and "Naya comment" in result.text and "Pehle ye karo" in result.text
    assert result.links == ["https://x/1"]
