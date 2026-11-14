"""Languages: table completeness, fallback, profiles, Marathi turns."""
from collections import defaultdict
from pathlib import Path

from remo import lang as L
from remo import turn
from remo.config import Settings
from remo.memory import Memory


def test_marathi_table_covers_every_hindi_key() -> None:
    assert set(L.MR) == set(L.HI), "every Hinglish string needs a Marathi twin"


def test_templates_format_cleanly() -> None:
    filler = defaultdict(str)
    for code in ("hi-IN", "mr-IN"):
        for key, template in L.strings(code).items():
            template.format_map(filler)  # must not raise


def test_unknown_locale_falls_back_to_hindi() -> None:
    assert L.strings("xx-YY")["ack_saved"] == L.HI["ack_saved"]
    assert L.strings(None)["ack_saved"] == L.HI["ack_saved"]
    assert L.profile("xx-YY")["tts_voice"] == "Nalini"


def test_profiles_and_voice_resolution() -> None:
    assert L.profile("hi-IN")["tts_voice"] == "Nalini"
    assert L.profile("mr-IN")["tts_voice"] == "Zahira"
    assert L.resolve_voice("", "mr-IN") == "Zahira"
    assert L.resolve_voice("Ishaan", "mr-IN") == "Ishaan"


def test_marathi_save_and_recall_turn(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    settings = Settings(gnani_api_key="test-key", language="mr-IN")
    saved = turn.handle_text("lakshat thev, ganitat integration zala", mem=mem, settings=settings, speak=False)
    assert saved.text == L.MR["ack_saved"]
    assert "integration" in mem.list_recent()[0].text
    asked = turn.handle_text("kay rahila aahe?", mem=mem, settings=settings, speak=False)
    assert asked.action == "left_off"
    assert "rahila" in asked.text or "Shevatchi" in asked.text
    mem.close()


def test_hindi_turns_unchanged(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    settings = Settings(gnani_api_key="test-key", language="hi-IN")
    saved = turn.handle_text("yaad rakhna test note", mem=mem, settings=settings, speak=False)
    assert saved.text == L.HI["ack_saved"]
    mem.close()


def test_second_person_flips_user_pronouns() -> None:
    assert L.to_second_person("mujhe kal yeh kaam karna hai") == "aapko kal yeh kaam karna hai"
    assert L.to_second_person("maine ghar ki safai ki") == "aapne ghar ki safai ki"
    assert L.to_second_person("mera kaam, mere paise, meri book") == "aapka kaam, aapke paise, aapki book"
    assert L.to_second_person("mujhse poocho, mujh ko batao") == "aapse poocho, aapko batao"
    assert L.to_second_person("mujhko bhi humein bhi") == "aapko bhi aapko bhi"
    assert L.to_second_person("mujhe kal 2 PR merge karne hain") == "aapko kal 2 PR merge karne hain"


def test_second_person_devanagari_and_marathi() -> None:
    assert L.to_second_person("मुझे कल यह काम करना है") == "आपको कल यह काम करना है"
    assert L.to_second_person("मैंने घर साफ किया, मेरा काम") == "आपने घर साफ किया, आपका काम"
    assert L.to_second_person("mala udya kam karaycha aahe") == "tumhala udya kam karaycha aahe"
    assert L.to_second_person("mazi book, maza phone") == "tumchi book, tumcha phone"


def test_second_person_leaves_lookalikes_alone() -> None:
    assert L.to_second_person("main gate par milo") == "main gate par milo"
    assert L.to_second_person("ghar mein meeting hai") == "ghar mein meeting hai"
    assert L.to_second_person("samajh gaya, kaam ho gaya") == "samajh gaya, kaam ho gaya"
    assert L.to_second_person("") == ""
