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
from remo.memory import Memory, Note, content_tokens, fold_text, fold_word

# Obligation verbs ("X karni hai" = X is still to do), enumerated per verb so
# lookalike nouns ("khana", "gana", "purana") never count as pending.
_PENDING_VERBS_LATIN = r"(?:karna|karni|karne|lena|leni|lene|dena|deni|dene|aana|aani|jaana|jaani|banana|banani|padhna|likhna|lana|pina)"
_PENDING_VERBS_DEVA = r"(?:करना|करनी|करने|लेना|लेनी|लेने|देना|देनी|देने|आना|आनी|जाना|जानी|बनाना|बनानी|पढ़ना|लिखना|लाना|पीना)"

_PENDING_PAT = re.compile(
    r"baaki|baki|bacha|bache|left|pending|reh gay|karne|to[\s-]?do|adhur"
    r"|\b" + _PENDING_VERBS_LATIN + r"\s+hain?\b"
    r"|बाकी|बकि|बचा|बचे|अधूर|रह ग|राहिल|करायच"
    r"|\b" + _PENDING_VERBS_DEVA + r"\s+हैं?",
    re.IGNORECASE,
)

_LEFT_OFF_MARKERS = (
    "kya bacha",
    "kya bache",
    "kya baaki",
    "kya baki",
    "kya task",
    "kya kaam",
    "kaun se task",
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

# Token rule for what phrases miss across scripts: a question word plus a
# left-over word, both in folded form ("क्या टास्क बचे" -> kya + task + bache).
_LEFT_Q_WORDS = frozenset(
    fold_word(w)
    for w in {"kya", "kaun", "kay", "kon", "what", "batao", "sanga", "sang", "tell", "show",
              "list", "dikhao", "dikha", "dakhava"}
)
_LEFT_WORDS = frozenset(
    fold_word(w)
    for w in {"bacha", "bache", "baaki", "baki", "pending", "left", "task", "tasks", "reh",
              "rahila", "shillak"}
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
    "क्या",
    "कब",
    "कौन",
    "किस",
    "कितना",
    "कितने",
    "कैसे",
    "क्यों",
    "क्यूं",
    "कहाँ",
    "बताओ",
    "सुनाओ",
    "काय",
    "केव्हा",
    "कोण",
    "कसा",
    "कशी",
    "सांगा",
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
    if any(marker in norm for marker in _LEFT_OFF_MARKERS):
        return True
    folded = fold_text(text)
    if any(fold_text(marker) in folded for marker in _LEFT_OFF_MARKERS):
        return True
    words = set(folded.split())
    return not words.isdisjoint(_LEFT_Q_WORDS) and not set(content_tokens(text)).isdisjoint(_LEFT_WORDS)


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


def compose_left_off(notes: list[Note], s: dict | None = None,
                     extra: list[str] | None = None) -> str:
    """Pending-first briefing over recent notes plus extra to-dos (e.g. work entries)."""
    s = s or lang_mod.HI
    pending = [n for n in notes if _PENDING_PAT.search(f"{n.text} {n.text_latin}")]
    shown = [_short(n.text) for n in pending[:3]]
    if extra:
        for item in extra:
            low = item.strip().lower()
            if low and not any(low in s.lower() or s.lower() in low for s in shown):
                shown.append(_short(item))
    if shown:
        items = "; ".join(shown[:4])
        tail_count = (len(notes) - len(pending)) + max(0, len(shown) - 4)
        tail = s["left_off_extra"].format(n=tail_count) if tail_count > 0 else ""
        return s["left_off_pending"].format(items=items) + tail
    if not notes:
        return s["left_off_none"]
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


def describe_note(note: Note, mem: Memory) -> str:
    """Machine facts about one note for the LLM composer ("due 2 din baad")."""
    bits: list[str] = []
    span, moment = reminders_mod.extract_time_mention(note.text)
    if span:
        bits.append(f"due {span.strip()}")
    if moment is not None and _has_matching_reminder(mem, moment):
        bits.append("a reminder is already set")
    elif _PENDING_PAT.search(f"{note.text} {note.text_latin}"):
        bits.append("still pending")
    return "; ".join(bits)


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
