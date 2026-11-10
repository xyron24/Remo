"""Extractive recall: find the right notes and say them back.

No LLM needed: left-off questions get pending-first answers composed from
stored notes, and general questions get the best matches read back. A reasoning
model can upgrade composition later without changing this interface.
"""
from __future__ import annotations

import re

from remo import lang as lang_mod
from remo import reminders as reminders_mod
from remo.brain_keywords import normalize
from remo.memory import Memory, Note

_PENDING_PAT = re.compile(
    r"baaki|baki|bacha|bache|left|pending|reh gay|karna hai|karne|to[\s-]?do|adhur"
    r"|बाकी|बकि|बचा|बचे|करना|करनी|करने|अधूर|रह ग|राहिल|करायच",
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
    """Token evidence first, trigram similarity only breaks ties.

    A note must share at least one topic token with the query to be returned;
    without that gate, raw trigram cosine ranks every note for every query and
    every question gets the same answer.
    """
    keyed = mem.token_hits(query, limit=limit)
    if not keyed:
        return []
    scores = {note.id: score for note, score in mem.search_vector(query, limit=len(keyed) + limit)}
    keyed.sort(key=lambda pair: (pair[1], scores.get(pair[0].id, 0.0), pair[0].id), reverse=True)
    return [note for note, _ in keyed[:limit]]


def is_left_off_query(text: str) -> bool:
    norm = normalize(text)
    return any(marker in norm for marker in _LEFT_OFF_MARKERS)


def is_recall_query(text: str) -> bool:
    if "?" in text:
        return True
    words = set(normalize(text).split())
    return not words.isdisjoint(_QUESTION_WORDS)


_TELL_ALL_MARKERS = (
    "kya yaad hai",
    "kya kya yaad hai",
    "kya yaad kiya",
    "kya yaad karwaya",
    "sab batao",
    "sab kuch batao",
    "sab kuch sunao",
    "sab sunao",
    "what do you remember",
    "what all do you remember",
    "tell me everything",
    "tell me all",
    "repeat everything",
    "repeat all",
    "recap",
    "kay lakshat thevla",
    "sagla sang",
    "sagla sanga",
    "sarva sang",
)


def is_tell_all_query(text: str) -> bool:
    """True for 'tell me everything you remember' with no topic."""
    norm = normalize(text)
    return any(marker in norm for marker in _TELL_ALL_MARKERS)


def _short(text: str, limit: int = _MAX_READ) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


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


def task_core(text: str, limit: int = 160) -> str:
    """The note minus its time mention and filler words ("UI update karna hai")."""
    task, _ = reminders_mod.split_task_time(text)
    return _short(task or text, limit)


def _has_matching_reminder(mem: Memory, moment) -> bool:
    try:
        target = moment.timestamp()
    except (AttributeError, OSError, OverflowError):
        return False
    return any(abs(r.fire_at - target) < 3600 for r in mem.list_armed())


def compose_answer(notes: list[Note], mem: Memory, s: dict | None = None) -> str:
    """Natural answer: what you said + when it is due + whether a reminder is set."""
    s = s or lang_mod.HI
    if not notes:
        return s["recall_none"]
    best = notes[0]
    parts = [s["answer_said"].format(task=task_core(best.text))]
    span, moment = reminders_mod.extract_time_mention(best.text)
    if span:
        parts.append(s["answer_due"].format(span=span.strip()))
    if moment is not None and _has_matching_reminder(mem, moment):
        parts.append(s["answer_reminded"].strip())
    elif _PENDING_PAT.search(f"{best.text} {best.text_latin}"):
        parts.append(s["answer_pending"].strip())
    elif len(notes) > 1:
        parts.append(s["recall_found"].format(items=_short(notes[1].text)))
    return " ".join(parts)
