"""Keyword gate: explicit triggers that save without interrogation.

Say "yaad rakhna …" / "remember …" (either script, at the very start) and
everything after it is stored. Anything else passes through to intent routing.
Voice confirmation survives only for destructive actions (forget/delete).
"""
from __future__ import annotations

import re
import unicodedata

SAVE_KEYWORDS = (
    "yaad rakhna", "remember", "याद रखना",
    "lakshat thev", "lakshat theva", "लक्षात ठेव", "लक्षात ठेवा",
)

_FORGET_PREFIXES = (
    "bhool jao", "bhula do", "forget", "भूल जाओ", "भुला दो",
    "visar", "visrun", "विसर", "विसरून",
)

_UNDO_LAST = frozenset(
    {
        "bhool jao last wali baat",
        "last wali baat bhool jao",
        "forget last",
        "forget the last one",
        "forget last note",
        "भूल जाओ आखिरी वाली बात",
        "आखिरी वाली बात भूल जाओ",
        "shevatchi goshta visar",
        "shevatchi goshta visrun ja",
        "शेवटची गोष्ट विसर",
    }
)

_SEPARATORS = " :,-–—"


def normalize(text: str) -> str:
    """Lowercase, whitespace-collapsed form used only for matching."""
    text = unicodedata.normalize("NFC", text.strip().lower())
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,!?;:")


def _tidy(text: str) -> str:
    """Original-cased text with whitespace collapsed, for storage."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text.strip()))


def match_save_keyword(text: str) -> str | None:
    """Content after an utterance-initial save keyword (original case), else None."""
    tidy = _tidy(text)
    lowered = tidy.lower()
    for keyword in SAVE_KEYWORDS:
        if lowered == keyword:
            return ""
        if lowered.startswith(keyword) and lowered[len(keyword)] in _SEPARATORS + " ":
            return tidy[len(keyword) :].lstrip(_SEPARATORS + " ")
    return None


def check_content(content: str) -> str | None:
    """None when storable, else the reason it must be asked again."""
    if not content or not content.strip():
        return "empty"
    if len(content.strip()) < 2:
        return "too-short"
    return None


def is_undo_last(text: str) -> bool:
    """True for exact 'forget the last thing I said' utterances."""
    return normalize(text) in _UNDO_LAST


def match_forget(text: str) -> str | None:
    """Forget target after a forget prefix (original case), else None."""
    tidy = _tidy(text)
    lowered = tidy.lower()
    for prefix in _FORGET_PREFIXES:
        if lowered.startswith(prefix) and len(lowered) > len(prefix) and lowered[len(prefix)] in _SEPARATORS + " ":
            target = tidy[len(prefix) :].lstrip(_SEPARATORS + " ")
            return target or None
    return None
