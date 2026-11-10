"""Extractive recall: find the right notes and say them back.

No LLM needed: left-off questions get pending-first answers composed from
stored notes, and general questions get the best matches read back. A reasoning
model can upgrade composition later without changing this interface.
"""
from __future__ import annotations

import re

from remo import lang as lang_mod
from remo.brain_keywords import normalize
from remo.memory import Memory, Note

_PENDING_PAT = re.compile(
    r"baaki|baki|bacha|bache|left|pending|reh gay|karna hai|to[\s-]?do|adhur",
    re.IGNORECASE,
)

_LEFT_OFF_MARKERS = (
    "kya bacha",
    "kya baaki",
    "kya baki",
    "kya reh gay",
    "kya chhuta",
    "what is left",
    "what's left",
    "whats left",
    "what is pending",
    "where did i leave off",
    "where was i",
    "kahan chhoda",
    "kay rahila",
    "kay baki",
    "kay shillak",
    "kay rahila aahe",
)

_QUESTION_WORDS = (
    "kya",
    "kab",
    "kaun",
    "kis",
    "kitna",
    "kitne",
    "kaise",
    "kyon",
    "kyun",
    "what",
    "when",
    "who",
    "whom",
    "whose",
    "how",
    "batao",
    "sunao",
    "kay",
    "kevha",
    "kon",
    "kasa",
    "kashi",
    "sanga",
    "sang",
)

_MAX_READ = 140


def hybrid_search(mem: Memory, query: str, limit: int = 5) -> list[Note]:
    """Keyword hits first, then meaning hits not already included."""
    found: list[Note] = []
    seen: set[int] = set()
    for note in mem.search_text(query, limit=limit):
        found.append(note)
        seen.add(note.id)
    for note, score in mem.search_vector(query, limit=limit):
        if note.id not in seen and score > 0.1:
            found.append(note)
            seen.add(note.id)
    return found[:limit]


def is_left_off_query(text: str) -> bool:
    norm = normalize(text)
    return any(marker in norm for marker in _LEFT_OFF_MARKERS)


def is_recall_query(text: str) -> bool:
    if "?" in text:
        return True
    words = set(normalize(text).split())
    return not words.isdisjoint(_QUESTION_WORDS)


def _short(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _MAX_READ else text[:_MAX_READ].rstrip() + "…"


def compose_left_off(notes: list[Note], s: dict | None = None) -> str:
    """Pending-first briefing over recent notes."""
    s = s or lang_mod.HI
    if not notes:
        return s["left_off_none"]
    pending = [n for n in notes if _PENDING_PAT.search(f"{n.text} {n.text_latin}")]
    if pending:
        items = "; ".join(_short(n.text) for n in pending[:3])
        extra = len(notes) - len(pending)
        tail = s["left_off_extra"].format(n=extra) if extra > 0 else ""
        return s["left_off_pending"].format(items=items) + tail
    return s["left_off_all_done"].format(latest=_short(notes[0].text))


def compose_recall(notes: list[Note], s: dict | None = None) -> str:
    """Read back the best matches, or admit nothing matched."""
    s = s or lang_mod.HI
    if not notes:
        return s["recall_none"]
    items = " ".join(_short(n.text) for n in notes[:3])
    return s["recall_found"].format(items=items)
