"""Local-first memory: notes, work entries, reminders, and learned lists.

SQLite holds every table; notes are also stored in a Latin transliteration plus
a meaning vector so "maths" can find "मैथ्स". Vectors come from a tiny offline
hashed embedder — no network, deterministic — behind a swappable interface.
Full-text search uses FTS5 when the local SQLite has it, else LIKE.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

EMBED_DIM = 256

_DEVA_TO_LATIN = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
    "।": ".", "॥": "..",
}

# Nukta consonants are two code points; fold them before the char-by-char pass.
_NUKTA_FOLD = {"क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f"}


def transliterate_latin(text: str) -> str:
    """Rough Devanagari→Latin fold (no schwa deletion). Latin passes through."""
    for combo, latin in _NUKTA_FOLD.items():
        text = text.replace(combo, latin)
    return "".join(_DEVA_TO_LATIN.get(ch, ch) for ch in text)


class HashEmbedder:
    """Deterministic offline embedder: char-trigram hashing, L2-normalized."""

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        padded = f"  {text.lower()}  "
        for i in range(len(padded) - 2):
            tri = padded[i : i + 3]
            idx = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def to_blob(self, vec: list[float]) -> bytes:
        return struct.pack(f"<{len(vec)}f", *vec)

    def from_blob(self, blob: bytes) -> list[float]:
        return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if not denom:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / denom


@dataclass
class Note:
    id: int
    text: str
    text_latin: str
    created_at: float
    source: str


@dataclass
class Reminder:
    id: int
    text: str
    fire_at: float
    armed: bool
    created_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    text_latin TEXT NOT NULL DEFAULT '',
    embedding BLOB,
    created_at REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'voice'
);
CREATE TABLE IF NOT EXISTS work_entries (
    id INTEGER PRIMARY KEY,
    persona TEXT NOT NULL DEFAULT 'student',
    org TEXT NOT NULL DEFAULT '',
    issue_ref TEXT NOT NULL DEFAULT '',
    done_json TEXT NOT NULL DEFAULT '[]',
    pending_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    fire_at REAL NOT NULL,
    armed INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS boost_words (
    word TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'hi',
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (word, lang)
);
CREATE TABLE IF NOT EXISTS fix_rules (
    pattern TEXT NOT NULL,
    replacement TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'hi',
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (pattern, lang)
);
CREATE TABLE IF NOT EXISTS watched_items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    cursor TEXT NOT NULL DEFAULT '',
    last_checked_at REAL NOT NULL DEFAULT 0,
    last_briefed_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    watched_id INTEGER NOT NULL REFERENCES watched_items(id),
    seen_at REAL NOT NULL,
    summary TEXT NOT NULL,
    source_quote TEXT NOT NULL DEFAULT '',
    source_link TEXT NOT NULL DEFAULT '',
    briefed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    text, text_latin, content='notes', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text, text_latin)
    VALUES (new.id, new.text, new.text_latin);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text, text_latin)
    VALUES ('delete', old.id, old.text, old.text_latin);
END;
"""


class Memory:
    def __init__(self, path: Path | str = ":memory:", embedder: HashEmbedder | None = None) -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        try:
            self.db.executescript(_FTS_SCHEMA)
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.embedder = embedder or HashEmbedder()

    def close(self) -> None:
        self.db.close()

    # -- notes ------------------------------------------------------------
    def add_note(self, text: str, source: str = "voice") -> Note:
        latin = transliterate_latin(text)
        blob = self.embedder.to_blob(self.embedder.embed(f"{text} {latin}"))
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO notes (text, text_latin, embedding, created_at, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (text, latin, blob, now, source),
        )
        self.db.commit()
        return Note(id=cur.lastrowid or 0, text=text, text_latin=latin, created_at=now, source=source)

    def get_note(self, note_id: int) -> Note | None:
        row = self.db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return self._note_from(row) if row else None

    def list_recent(self, limit: int = 20) -> list[Note]:
        rows = self.db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._note_from(r) for r in rows]

    def forget_note(self, note_id: int) -> bool:
        cur = self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.db.commit()
        return cur.rowcount > 0

    def forget_last_note(self) -> Note | None:
        rows = self.db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 1").fetchone()
        if rows is None:
            return None
        note = self._note_from(rows)
        self.forget_note(note.id)
        return note

    def search_text(self, query: str, limit: int = 10) -> list[Note]:
        """Keyword search over both scripts; LIKE fallback when FTS5 is missing."""
        if self.fts:
            phrase = '"' + query.replace('"', '""') + '"'
            try:
                rows = self.db.execute(
                    "SELECT n.* FROM notes_fts f JOIN notes n ON n.id = f.rowid"
                    " WHERE notes_fts MATCH ? LIMIT ?",
                    (phrase, limit),
                ).fetchall()
                return [self._note_from(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        like = f"%{query}%"
        rows = self.db.execute(
            "SELECT * FROM notes WHERE text LIKE ? OR text_latin LIKE ?"
            " ORDER BY id DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [self._note_from(r) for r in rows]

    def search_vector(self, query: str, limit: int = 10) -> list[tuple[Note, float]]:
        """Meaning search: cosine rank over stored embeddings."""
        latin = transliterate_latin(query)
        qvec = self.embedder.embed(f"{query} {latin}")
        scored: list[tuple[Note, float]] = []
        for row in self.db.execute("SELECT * FROM notes").fetchall():
            blob = row["embedding"]
            if not blob:
                continue
            score = cosine(qvec, self.embedder.from_blob(blob))
            scored.append((self._note_from(row), score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    # -- learned lists ----------------------------------------------------
    def set_boost_words(self, words: list[str], lang: str = "hi") -> None:
        self.db.execute("DELETE FROM boost_words WHERE lang = ?", (lang,))
        self.db.executemany(
            "INSERT INTO boost_words (word, lang) VALUES (?, ?)", [(w, lang) for w in words]
        )
        self.db.commit()

    def get_boost_words(self, lang: str = "hi") -> list[str]:
        rows = self.db.execute(
            "SELECT word FROM boost_words WHERE lang = ? AND active = 1", (lang,)
        ).fetchall()
        return [r["word"] for r in rows]

    def add_fix_rule(self, pattern: str, replacement: str, lang: str = "hi") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO fix_rules (pattern, replacement, lang) VALUES (?, ?, ?)",
            (pattern, replacement, lang),
        )
        self.db.commit()

    def get_fix_rules(self, lang: str = "hi") -> list[tuple[str, str]]:
        rows = self.db.execute(
            "SELECT pattern, replacement FROM fix_rules WHERE lang = ? AND active = 1", (lang,)
        ).fetchall()
        return [(r["pattern"], r["replacement"]) for r in rows]

    # -- reminders ------------------------------------------------------
    def add_reminder(self, text: str, fire_at: float) -> Reminder:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO reminders (text, fire_at, armed, created_at) VALUES (?, ?, 1, ?)",
            (text, fire_at, now),
        )
        self.db.commit()
        return Reminder(id=cur.lastrowid or 0, text=text, fire_at=fire_at, armed=True, created_at=now)

    def list_armed(self, before: float | None = None) -> list[Reminder]:
        if before is None:
            rows = self.db.execute("SELECT * FROM reminders WHERE armed = 1 ORDER BY fire_at").fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM reminders WHERE armed = 1 AND fire_at <= ? ORDER BY fire_at", (before,)
            ).fetchall()
        return [self._reminder_from(r) for r in rows]

    def disarm(self, reminder_id: int) -> bool:
        cur = self.db.execute("UPDATE reminders SET armed = 0 WHERE id = ?", (reminder_id,))
        self.db.commit()
        return cur.rowcount > 0

    def delete_reminder(self, reminder_id: int) -> bool:
        cur = self.db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self.db.commit()
        return cur.rowcount > 0

    # -- settings ---------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _reminder_from(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            text=row["text"],
            fire_at=row["fire_at"],
            armed=bool(row["armed"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _note_from(row: sqlite3.Row) -> Note:
        return Note(
            id=row["id"],
            text=row["text"],
            text_latin=row["text_latin"],
            created_at=row["created_at"],
            source=row["source"],
        )

    @staticmethod
    def dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)
