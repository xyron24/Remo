"""Work-log: parsing, refs, personas, merge, composition."""
from pathlib import Path

from remo import worklog as W
from remo.memory import Memory


def test_parse_done_pending_split() -> None:
    parsed = W.parse_update("login fix ho gaya, tests ho gaye, docs baaki hai")
    assert parsed.done == ["login fix ho gaya", "tests ho gaye"]
    assert parsed.pending == ["docs baaki hai"]


def test_unmarked_clause_defaults_to_pending() -> None:
    parsed = W.parse_update("caching wala comment")
    assert parsed.pending == ["caching wala comment"] and parsed.done == []


def test_detect_refs() -> None:
    assert W.detect_refs("org Mifos, issue 214 update") == ("Mifos", "214")
    assert W.detect_refs("PR #220 merge ho gaya") == ("", "220")
    assert W.detect_refs("aaj mausam achha hai") == ("", "")


def test_is_work_update() -> None:
    assert W.is_work_update("GSoC update: login fix ho gaya, docs baaki") is True
    assert W.is_work_update("issue 214 mein caching comment pending hai") is True
    assert W.is_work_update("kal kirana se atta lena hai") is False
    assert W.is_work_update("maths mein integration ho gaya") is False


def test_detect_persona() -> None:
    assert W.detect_persona("khet mein sinchai baaki hai") == "kisan"
    assert W.detect_persona("Ramesh ka udhaar lena hai") == "dukandaar"
    assert W.detect_persona("garbhvati ka checkup karna hai") == "asha"
    assert W.detect_persona("GSoC update: docs baaki") == "student"


def test_store_merges_and_graduates_pending(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    W.store_update(mem, "org Mifos issue 214: login fix ho gaya, docs baaki hai")
    entry = W.store_update(mem, "issue 214: docs ho gaye, caching comment baaki hai")
    assert "login fix ho gaya" in entry.done and "docs ho gaye" in entry.done
    assert "docs baaki hai" not in entry.pending  # graduated out once done
    assert "caching comment baaki hai" in entry.pending
    assert entry.org == "Mifos" and entry.issue_ref == "214"
    mem.close()


def test_compose_entry_pending_first(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    entry = W.store_update(mem, "org Mifos issue 214: login fix ho gaya, docs baaki hai")
    say = W.compose_entry(entry)
    assert "baaki" in say and say.index("docs") < say.index("Ho gaya")
    mem.close()


def test_welcome_back_merges_pending_and_deltas(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    W.store_update(mem, "issue 214: docs baaki hai")
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/214")
    mem.store_changes(watched.id, [("Naya comment aaya.", "LGTM", "https://x/y#c1", 1.0)])
    say, links = W.compose_welcome_back(mem.list_work_entries(), mem.unbriefed_changes())
    assert "Welcome back" in say and "docs" in say and "Naya comment" in say
    assert "Pehle ye karo" in say and links == ["https://x/y#c1"]
    mem.close()


def test_welcome_back_empty_state(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    say, links = W.compose_welcome_back([], [])
    assert "Kuch baaki nahi" in say and links == []
    mem.close()
