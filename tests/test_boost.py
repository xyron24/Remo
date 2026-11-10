"""Boost list building, fix rules, learned snapshot."""
from pathlib import Path

from remo import boost as B
from remo.memory import Memory
from remo.stt import valid_boost_words


def test_boost_list_ranks_frequent_meaningful_words(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("maths mein integration ho gaya")
    mem.add_note("maths mein differentiation baaki hai")
    words = B.build_boost_list(mem)
    assert words[0] == "maths"
    assert "mein" not in words and "hai" not in words
    assert words == valid_boost_words(words), "built list must pass Prisma validation"
    mem.close()


def test_boost_list_includes_work_vocab(tmp_path: Path) -> None:
    from remo import worklog as W

    mem = Memory(tmp_path / "remo.db")
    W.store_update(mem, "org Mifos issue 214: login fix ho gaya")
    assert "mifos" in B.build_boost_list(mem)
    mem.close()


def test_refresh_persists(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("viva ki taiyari karni hai")
    stored = B.refresh_boost_words(mem)
    assert "viva" in stored and "viva" in mem.get_boost_words()
    mem.close()


def test_fix_rules_apply_and_count() -> None:
    fixed, count = B.apply_fix_rules("kal vivaah hai", [("vivaah", "viva")])
    assert (fixed, count) == ("kal viva hai", 1)
    fixed, count = B.apply_fix_rules("sab theek hai", [("vivaah", "viva")])
    assert (fixed, count) == ("sab theek hai", 0)


def test_snapshot_shape(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.set_boost_words(["viva"])
    mem.add_fix_rule("vivaah", "viva")
    snap = B.snapshot(mem)
    assert snap == {"boost_words": ["viva"], "fix_rules": [("vivaah", "viva")]}
    mem.close()
