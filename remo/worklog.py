"""Work-log memory: spoken progress becomes done/pending structure.

"GSoC update: login fix ho gaya, docs baaki hai" becomes a structured entry the
user can query days later ("issue 214 mein kya bacha hai?"). Extractive —
marker phrases split clauses into done vs pending, per persona.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from remo.brain_keywords import normalize
from remo.memory import Change, Memory, WatchedItem, WorkEntry

PERSONAS = ("student", "kisan", "dukandaar", "asha")

_DONE_MARKERS = (
    "ho gaya", "ho gaye", "ho gayi", "kar liya", "kar liye", "kar diya", "kar diye",
    "kiya", "kiye", "kii", "gaya", "gaye", "gayi", "liya", "liye", "diya", "diye",
    "banaya", "banaye", "likha", "likhe", "bheja", "padha", "dekha", "khatm",
    "done", "completed", "finished", "fixed", "merged", "implemented", "tested",
    "deployed", "closed", "resolved", "shipped", "wrote", "added", "updated",
)

_PENDING_MARKERS = (
    "baaki", "baki", "bacha", "bache", "bachi", "reh gaya", "reh gaye", "reh gayi",
    "karna hai", "karni hai", "karne hain", "adhura", "adhuri", "adhure",
    "left", "pending", "remaining", "todo", "to-do", "to do", "next", "will do",
)

_PERSONA_DONE = {
    "kisan": ("boya", "boye", "kaata", "kaate", "dala", "daala", "seecha"),
    "dukandaar": ("becha", "beche", "aaya maal", "hisab kiya", "hisaab kiya"),
    "asha": ("teeka lagaya", "vaccine diya", "jaanch ki", "checkup kiya"),
    "student": (),
}

_PERSONA_PENDING = {
    "kisan": ("boni", "sinchai", "spray karna", "khaad dalna", "mandi jana"),
    "dukandaar": ("maal mangana", "udhaar lena", "stock lena", "hisab karna"),
    "asha": ("visit karna", "teeka lagana", "report bhejna"),
    "student": (),
}

_PERSONA_HINTS = {
    "kisan": ("fasal", "khet", "beej", "khaad", "sinchai", "spray", "mandi", "boni", "kheti"),
    "dukandaar": ("udhaar", "stock", "dukaan", "grahak", "hisaab", "hisab", "khata", "maal", "bikri"),
    "asha": ("asha", "garbhvati", "vaccine", "teeka", "visit", "swasthya", "hospital", "dawai"),
}

_SPLIT_PAT = re.compile(r"\s*(?:,|;| aur | or | phir | then |\. )\s*", re.IGNORECASE)
_ORG_PAT = re.compile(r"\borg\s+([A-Za-z][\w-]*)", re.IGNORECASE)
_ISSUE_PAT = re.compile(r"(?:issue|mudda|pr|pull request)?\s*#(\d+)", re.IGNORECASE)
_ISSUE_WORD_PAT = re.compile(r"\b(?:issue|pr|pull request)\s+(\d+)", re.IGNORECASE)

_REF_CLEAN_PATS = (
    re.compile(r"\borg\s+[A-Za-z][\w-]*", re.IGNORECASE),
    re.compile(r"\b(?:issue|mudda|pr|pull request)\s+#?\d+\s*(?:mein\s*)?", re.IGNORECASE),
    re.compile(r"#\d+"),
    re.compile(r"^[\w\s]*?\b(?:update|progress)\s*:\s*", re.IGNORECASE),
)


def _strip_refs(text: str) -> str:
    """Remove ref preambles so structured clauses read clean ("docs baaki hai")."""
    for pattern in _REF_CLEAN_PATS:
        text = pattern.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ParsedUpdate:
    done: list[str]
    pending: list[str]


def detect_persona(text: str) -> str:
    norm = normalize(text)
    best, best_hits = "student", 0
    for persona, hints in _PERSONA_HINTS.items():
        hits = sum(1 for hint in hints if hint in norm)
        if hits > best_hits:
            best, best_hits = persona, hits
    return best


def detect_refs(text: str) -> tuple[str, str]:
    """(org, issue_ref) explicitly named in the text; "" when absent."""
    org_match = _ORG_PAT.search(text)
    org = org_match.group(1) if org_match else ""
    issue_match = _ISSUE_WORD_PAT.search(text) or _ISSUE_PAT.search(text)
    ref = issue_match.group(1) if issue_match else ""
    return org, ref


def _markers(persona: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    done = _DONE_MARKERS + _PERSONA_DONE.get(persona, ())
    pending = _PENDING_MARKERS + _PERSONA_PENDING.get(persona, ())
    return done, pending


def parse_update(text: str, persona: str = "student") -> ParsedUpdate:
    """Split an update into done vs pending clauses (unmarked -> pending)."""
    done_markers, pending_markers = _markers(persona)
    done, pending = [], []
    for clause in _SPLIT_PAT.split(_strip_refs(text)):
        clause = clause.strip(" .,!?;:")
        if not clause:
            continue
        lowered = clause.lower()
        if any(marker in lowered for marker in pending_markers):
            pending.append(clause)
        elif any(marker in lowered for marker in done_markers):
            done.append(clause)
        else:
            pending.append(clause)  # a memory aid errs toward reminding
    return ParsedUpdate(done=done, pending=pending)


def is_work_update(text: str) -> bool:
    """True when the text reads as a progress update, not a plain note."""
    norm = normalize(text)
    has_ref = bool(_ORG_PAT.search(text) or _ISSUE_WORD_PAT.search(text) or _ISSUE_PAT.search(text))
    has_update_word = "update" in norm or "progress" in norm or "project" in norm
    if not (has_ref or has_update_word):
        return False
    done_markers, pending_markers = _markers(detect_persona(text))
    return any(m in norm for m in done_markers + pending_markers)


_CORE_FILLERS = frozenset(
    {"hai", "hain", "hun", "hoon", "tha", "thi", "thay", "the", "ko", "ka", "ki", "ke",
     "mein", "ne", "se", "par", "ka", "aur", "wala", "wali", "wale", "a", "an"}
)


def _core_words(clause: str) -> set[str]:
    """Content words minus done/pending marker phrases ("docs baaki hai" -> {"docs"})."""
    lowered = clause.lower()
    for marker in _DONE_MARKERS + _PENDING_MARKERS:
        lowered = lowered.replace(marker, " ")
    return {
        w for w in re.findall(r"[a-zA-Z\u0900-\u097F]+", lowered)
        if len(w) >= 3 and w not in _CORE_FILLERS
    }


def _graduated(pending_item: str, done_new: list[str]) -> bool:
    """A pending item graduates when a new done item covers the same core."""
    core = _core_words(pending_item)
    return bool(core) and any(_core_words(d) == core for d in done_new)


def store_update(mem: Memory, text: str, persona: str | None = None) -> WorkEntry:
    """Parse and merge a spoken update into the matching work entry."""
    persona = persona or detect_persona(text)
    org, ref = detect_refs(text)
    parsed = parse_update(text, persona)
    existing = mem.find_work_entry(org, ref)
    if existing is None:
        return mem.upsert_work_entry(persona, org, ref, parsed.done, parsed.pending)
    merged_done = existing.done + [d for d in parsed.done if d not in existing.done]
    kept = [p for p in existing.pending if not _graduated(p, parsed.done)]
    merged_pending = kept + [p for p in parsed.pending if p not in kept]
    return mem.update_work_entry(existing.id, merged_done, merged_pending)


def _label(entry: WorkEntry) -> str:
    bits = [b for b in (entry.org, f"issue {entry.issue_ref}" if entry.issue_ref else "") if b]
    return " ".join(bits) if bits else "ye kaam"


def compose_entry(entry: WorkEntry) -> str:
    """Pending-first briefing for one work entry."""
    label = _label(entry)
    if not entry.pending and not entry.done:
        return f"{label} mein abhi kuch darj nahi hai."
    parts = []
    if entry.pending:
        parts.append(f"{label} mein ye baaki hai: {'; '.join(entry.pending[:4])}.")
    if entry.done:
        parts.append(f"Ho gaya: {'; '.join(entry.done[:4])}.")
    return " ".join(parts)


def compose_welcome_back(
    entries: list[WorkEntry], deltas: list[tuple[WatchedItem, list[Change]]]
) -> tuple[str, list[str]]:
    """Your pending items + the world's changes + a suggested next step."""
    pending_all: list[str] = [p for entry in entries for p in entry.pending[:3]]
    total_changes = sum(len(changes) for _, changes in deltas)
    links = [c.source_link for _, changes in deltas for c in changes if c.source_link]

    if not pending_all and total_changes == 0:
        return "Welcome back! Kuch baaki nahi hai aur bahar bhi koi badlaav nahi.", []
    parts = ["Welcome back!"]
    if pending_all:
        parts.append(f"Aapke {len(pending_all)} kaam baaki hain: {'; '.join(pending_all[:4])}.")
    if total_changes:
        firsts = "; ".join(c.summary for _, changes in deltas for c in changes[:2])
        parts.append(f"Bahar {total_changes} badlaav aaye hain: {firsts}.")
    if pending_all:
        parts.append(f"Pehle ye karo: {pending_all[0]}.")
    return " ".join(parts), links
