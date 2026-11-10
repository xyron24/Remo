"""Extractive recall: find the right notes and say them back.

No LLM needed: left-off questions get pending-first answers composed from
stored notes, and general questions get the best matches read back. A reasoning
model can upgrade composition later without changing this interface.
"""
from __future__ import annotations

import re

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


def compose_left_off(notes: list[Note]) -> str:
    """Pending-first briefing over recent notes."""
    if not notes:
        return "Abhi maine kuch yaad nahi kiya. 'Yaad rakhna' bolkar shuru karo."
    pending = [n for n in notes if _PENDING_PAT.search(f"{n.text} {n.text_latin}")]
    if pending:
        items = "; ".join(_short(n.text) for n in pending[:3])
        extra = len(notes) - len(pending)
        tail = f" Aur {extra} purani baatein yaad hain." if extra > 0 else ""
        return f"Ye baaki hai: {items}.{tail}"
    return f"Kuch baaki nahi dikh raha. Aakhri baat thi: {_short(notes[0].text)}."


def compose_recall(notes: list[Note]) -> str:
    """Read back the best matches, or admit nothing matched."""
    if not notes:
        return "Is baare mein mujhe kuch yaad nahi hai."
    items = " ".join(_short(n.text) for n in notes[:3])
    return f"Mujhe ye mila: {items}"
