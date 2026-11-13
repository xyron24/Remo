"""Memory: notes CRUD, dual-script search, vectors, learned lists."""
from pathlib import Path

from remo.memory import (
    EMBED_DIM,
    HashEmbedder,
    Memory,
    content_tokens,
    cosine,
    fold_text,
    transliterate_latin,
)


def test_add_get_list_and_forget(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    first = mem.add_note("maths mein integration ho gaya")
    mem.add_note("Go assignment kal hai")
    assert mem.get_note(first.id) is not None
    assert [n.id for n in mem.list_recent()] == sorted(
        [n.id for n in mem.list_recent()], reverse=True
    )
    assert mem.forget_note(first.id) is True
    assert mem.get_note(first.id) is None
    assert mem.forget_note(999999) is False
    mem.close()


def test_forget_last_note(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    assert mem.forget_last_note() is None
    mem.add_note("pehli baat")
    last = mem.add_note("aakhri baat")
    forgotten = mem.forget_last_note()
    assert forgotten is not None and forgotten.id == last.id
    assert mem.get_note(last.id) is None
    mem.close()


def test_transliteration_spot_checks() -> None:
    assert transliterate_latin("मैथ्स") == "maiths"
    assert transliterate_latin("नमस्ते") == "namaste"
    assert transliterate_latin("कल घर की सफाई") == "kal ghar kee saphaaee"
    assert transliterate_latin("hello") == "hello"


def test_content_tokens_bridge_latin_and_devanagari() -> None:
    latin = set(content_tokens("kal ghar ki safai krni hai?"))
    deva = set(content_tokens("मुझे कल घर की सफाई करनी है।"))
    assert {"kal", "ghar", "safai"} <= latin & deva


def test_fold_text_and_chandrakala_o() -> None:
    assert fold_text("क्या बचा है") == "kya bacha hai"
    assert fold_text("याद दिला देना") == "yad dila dena"
    assert transliterate_latin("वॉच") == "voch"


def test_notes_carry_latin_fold_and_embedding(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    note = mem.add_note("याद रखना parallel test")
    assert "yaad" in note.text_latin
    row = mem.db.execute("SELECT embedding FROM notes WHERE id = ?", (note.id,)).fetchone()
    assert row["embedding"] is not None and len(row["embedding"]) == EMBED_DIM * 4
    mem.close()


def test_text_search_same_script(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("differential equations baaki hai")
    mem.add_note("kal kirana se atta lena hai")
    hits = mem.search_text("differential")
    assert len(hits) == 1 and "differential" in hits[0].text
    mem.close()


def test_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashEmbedder()
    vec = embedder.embed("maths integration")
    assert len(vec) == EMBED_DIM
    assert embedder.embed("maths integration") == vec  # deterministic
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-6  # unit length
    assert abs(cosine(vec, vec) - 1.0) < 1e-6
    assert cosine(vec, embedder.embed("kirana atta dal")) < 1.0


def test_vector_search_ranks_best_match_first(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.add_note("maths mein integration ho gaya")
    mem.add_note("kirana se atta aur dal lena hai")
    ranked = mem.search_vector("integration maths")
    assert ranked and "integration" in ranked[0][0].text
    mem.close()


def test_boost_words_and_fix_rules(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.set_boost_words(["viva", "Mifos"])
    assert mem.get_boost_words() == ["viva", "Mifos"]
    mem.set_boost_words(["quiz"])
    assert mem.get_boost_words() == ["quiz"]
    mem.add_fix_rule("विवाह", "viva")
    assert mem.get_fix_rules() == [("विवाह", "viva")]
    mem.close()


def test_delete_work_entry(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    entry = mem.upsert_work_entry("student", "Mifos", "214", [], ["docs"])
    assert mem.delete_work_entry(entry.id) is True
    assert mem.delete_work_entry(entry.id) is False
    assert mem.list_work_entries() == []
    mem.close()


def test_unwatch_removes_item_and_changes(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/1")
    mem.store_changes(watched.id, [("Naya comment.", "q", "https://x/1", 1.0)])
    assert mem.unwatch(watched.id) is True
    assert mem.unwatch(watched.id) is False
    assert mem.list_watched() == []
    assert mem.recent_changes() == []
    mem.close()
