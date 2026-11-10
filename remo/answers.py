"""Spoken yes/no: every spelling of haan and nahi, in both scripts.

Returns True / False / None (unclear). Callers must ask again on None —
never guess "no".
"""
from __future__ import annotations

from remo.brain_keywords import normalize

YES_WORDS = frozenset(
    {
        "haan", "han", "ha", "haanji", "hanji", "ji",
        "yes", "yeah", "yep", "yup", "ok", "okay", "sure", "done", "pakka",
        "हाँ", "हां", "हान", "हा", "जी", "हाँजी",
    }
)

NO_WORDS = frozenset(
    {
        "nahi", "nahin", "nhi", "no", "nope", "never", "cancel",
        "नहीं", "नही", "ना",
    }
)

YES_PHRASES = ("theek hai", "thik hai", "kar do", "haan kar do", "bilkul")

NO_PHRASES = ("mat karo", "rehne do", "rehne de", "no thanks", "bilkul nahi")

UNCLEAR_PHRASES = ("pata nahi", "malum nahi", "maloom nahi", "don't know", "dont know", "samajh nahi", "kya kaha")


def parse_yes_no(text: str) -> bool | None:
    """True for yes, False for no, None when unclear or contradictory."""
    norm = normalize(text)
    if norm in ("na", "ना"):  # bare "na" is no; mid-sentence "na" is a softener
        return False
    if any(phrase in norm for phrase in UNCLEAR_PHRASES):
        return None
    words = set(norm.split())
    yes = not words.isdisjoint(YES_WORDS) or any(p in norm for p in YES_PHRASES)
    no = not words.isdisjoint(NO_WORDS) or any(p in norm for p in NO_PHRASES)
    if yes and no:
        return None
    if yes:
        return True
    if no:
        return False
    return None
