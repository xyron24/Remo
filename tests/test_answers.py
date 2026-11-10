"""Spoken yes/no across spellings and scripts."""
import pytest

from remo.answers import parse_yes_no


@pytest.mark.parametrize(
    "said",
    ["haan", "Haan", "han", "ha", "haanji", "yes", "yeah", "yep", "ok", "theek hai", "kar do",
     "हाँ", "हां", "हान", "जी"],
)
def test_yes_variants(said: str) -> None:
    assert parse_yes_no(said) is True


@pytest.mark.parametrize(
    "said",
    ["nahi", "nahin", "no", "nope", "mat karo", "rehne do", "na", "नहीं", "नही", "ना"],
)
def test_no_variants(said: str) -> None:
    assert parse_yes_no(said) is False


@pytest.mark.parametrize(
    "said",
    ["haan nahi", "maybe", "pata nahi", "kya?", "", "batao na", "dekho na"],
)
def test_unclear_is_none(said: str) -> None:
    assert parse_yes_no(said) is None
