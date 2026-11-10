"""Learning loop: your words teach Prisma to hear you better.

Vocabulary from your own notes becomes a word-boost list (frequency-ranked,
validated so one bad word can't nuke the list), and persistent mishearings
become find-and-replace rules. `snapshot` shows everything learned.
"""
from __future__ import annotations

import re
from collections import Counter

from remo.memory import Memory
from remo.quiz import STOPWORDS

_TOKEN_PAT = re.compile(r"[A-Za-z\u0900-\u097F]+")


def _tokens(text: str) -> list[str]:
    return [
        token for token in _TOKEN_PAT.findall(text.lower())
        if len(token) >= 3 and token.isalpha() and token not in STOPWORDS
    ]


def build_boost_list(mem: Memory, limit: int = 100) -> list[str]:
    """Frequency-ranked vocabulary from notes + work entries (stable order)."""
    counts: Counter[str] = Counter()
    for note in mem.list_recent(500):
        counts.update(_tokens(f"{note.text} {note.text_latin}"))
    for entry in mem.list_work_entries(limit=100):
        counts.update(_tokens(f"{entry.org} {entry.issue_ref}"))
        for item in entry.done + entry.pending:
            counts.update(_tokens(item))
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word for word, _ in ranked[:limit]]


def refresh_boost_words(mem: Memory, lang: str = "hi", limit: int = 100) -> list[str]:
    """Rebuild and persist the boost list; returns what was stored."""
    words = build_boost_list(mem, limit)
    mem.set_boost_words(words, lang)
    return words


def apply_fix_rules(text: str, rules: list[tuple[str, str]]) -> tuple[str, int]:
    """Apply learned find-and-replace rules; returns (fixed, applied_count)."""
    applied = 0
    for pattern, replacement in rules:
        fixed, count = re.subn(
            rf"\b{re.escape(pattern)}\b", replacement, text, flags=re.IGNORECASE
        )
        if count:
            text, applied = fixed, applied + count
    return text, applied


def snapshot(mem: Memory, lang: str = "hi") -> dict[str, object]:
    """Everything Remo learned: boost words + fix rules (for the UI)."""
    return {"boost_words": mem.get_boost_words(lang), "fix_rules": mem.get_fix_rules(lang)}
