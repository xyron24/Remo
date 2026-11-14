"""Local-first memory: notes, work entries, reminders, and learned lists.

SQLite holds every table; notes are also stored in a Latin transliteration plus
a meaning vector so "kal" can find "कल". Vectors come from a tiny offline
hashed embedder , no network, deterministic , behind a swappable interface.
Keyword search is token overlap over both scripts with stopwords dropped, so a
query only matches notes it actually shares words with.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

EMBED_DIM = 256

_DEVA_BASE = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}

_DEVA_SIGNS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ॉ": "o",
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ँ": "n", "ः": "h",
}

_DEVA_OTHER = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
    "।": ".", "॥": "..", "्": "", "़": "",
}

# Nukta consonants are two code points; the loop reads consonant + nukta as one.
_NUKTA_BASE = {"क": "q", "ख": "kh", "ग": "gh", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f"}

_VOWELS = frozenset("aeiou")


def _delete_schwa(word: str) -> str:
    """Hindi schwa deletion, simplified: final 'a' after a consonant goes, and
    a medial 'a' in an open syllable (consonant + 'a' + consonant + vowel) goes
    everywhere except the first syllable. Long 'aa' is never touched."""
    if len(word) > 2 and word.endswith("a") and word[-2] not in _VOWELS:
        word = word[:-1]
    res: list[str] = []
    seen_vowel = False
    n = len(word)
    for i, c in enumerate(word):
        if c in _VOWELS:
            medial = (
                c == "a"
                and seen_vowel
                and i > 0
                and word[i - 1] not in _VOWELS
                and i + 2 < n
                and word[i + 1] not in _VOWELS
                and word[i + 2] in _VOWELS
            )
            if not medial:
                res.append(c)
            seen_vowel = True
        else:
            res.append(c)
    return "".join(res)


def _transliterate_word(word: str) -> str:
    """One word: consonants carry inherent 'a' unless a halant kills it or a
    matra replaces it; nukta consonants map to their Urdu sounds."""
    out: list[str] = []
    i, n = 0, len(word)
    while i < n:
        ch = word[i]
        if ch in _DEVA_BASE:
            base = _DEVA_BASE[ch]
            j = i + 1
            if j < n and word[j] == "़":
                base = _NUKTA_BASE.get(ch, base)
                j += 1
            if j < n and word[j] == "्":
                out.append(base)
                i = j + 1
                continue
            if j < n and word[j] in _DEVA_SIGNS:
                out.append(base)
                i = j
                continue
            out.append(base + "a")
            i = j
            continue
        out.append(_DEVA_SIGNS.get(ch, _DEVA_OTHER.get(ch, ch)))
        i += 1
    return _delete_schwa("".join(out))


def transliterate_latin(text: str) -> str:
    """Devanagari→Latin with inherent vowels and schwa deletion.

    Only words containing Devanagari are touched, so Latin spellings pass
    through byte-identical: कल→kal, घर→ghar, नमस्ते→namaste.
    """
    parts = re.split(r"(\s+)", text)
    for k, part in enumerate(parts):
        if part and not part.isspace() and any("\u0900" <= c <= "\u097f" for c in part):
            parts[k] = _transliterate_word(part)
    return "".join(parts)


# Function words that carry no topic: dropped before overlap scoring so they
# can never match a note by themselves. Content words stay, in every language.
_STOPWORDS = frozenset(
    """
    mujhe mujhko mujhse main mein mene maine mera mere meri hum hamari hamare tum tumhe tumhara
    aap aapko ye yeh is iss us uss woh wo vo ka ke ki ko se par per tak ne bhi
    bhee hi hee toh to aur ya lekin hai hain tha thi the ho hoga hogi hoge honge
    hua hui hue hona hone hota hoti hote hu hun hoon raha rahi rahe kya kab kaun
    kis kisko kitna kitne kitni kaise kyon kyun kahan kidhar kyu batao bata sunao
    suna bolo bol jara zara bhi han man aaj liye abhi
    what when where which who whom whose why how the a an is are was were be been
    being to of and or in on for with at by from as that this these those it its i
    me my mine you your yours he him his she her we us our they them their have
    has had having do does did doing will would shall should can could may might
    must not no yes so very just now about into over after before up upon out also too
    some any more most other such than then there here
    mala maza majha majhya tumhi tumcha aamhi aamcha he hi ha hya tya te ti to kay
    kevha kuthe kon konala kasa kashi kase kiti aani ahe aahe aahet hota hoti hote
    hoto sanga sang
    """.split()
)


# Spelling bridges, applied to both sides before matching: सफाई/ph meets
# safai/f, वाला/v meets wala/w, की/kee meets ki, चाय/chaay meets chai.
_LOOSE_FOLD = (("ph", "f"), ("w", "v"), ("aa", "a"), ("ee", "i"), ("oo", "u"), ("ay", "ai"))


def _loose(tok: str) -> str:
    for old, new in _LOOSE_FOLD:
        tok = tok.replace(old, new)
    return tok


def fold_word(word: str) -> str:
    """One natural-spelling word into folded space ("what" -> "vhat").

    Matcher sets are written naturally and folded once, so hand-written sets
    can never drift from what the fold actually produces.
    """
    return _loose(word.lower())


def fold_text(text: str) -> str:
    """Whole-text loose-Latin fold for intent matching ("क्या बचा" -> "kya bacha").

    Unlike content_tokens, nothing is dropped: question words survive so
    classifiers can see them in either script.
    """
    return " ".join(
        _loose(tok) for tok in re.findall(r"[a-z0-9]+", transliterate_latin(text).lower())
    )


def content_tokens(text: str) -> list[str]:
    """Topic tokens: Devanagari folded to Latin, spellings bridged, stopwords
    dropped. Digits always count ("2 din baad"); alpha tokens need 2+ letters
    so bare "a"/"e" cannot match. Same function on both sides keeps
    cross-script matching exact.
    """
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9]+", transliterate_latin(text).lower()):
        if tok.isdigit() or len(tok) >= 2:
            folded = _loose(tok)
            if folded not in _STOPWORDS:
                out.append(folded)
    return out


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


@dataclass
class WorkEntry:
    id: int
    persona: str
    org: str
    issue_ref: str
    done: list[str]
    pending: list[str]
    created_at: float
    updated_at: float


@dataclass
class User:
    id: int
    email: str
    name: str
    avatar_url: str
    provider: str
    password_hash: str
    created_at: float


@dataclass
class WatchedItem:
    id: int
    kind: str
    url: str
    cursor: str
    last_checked_at: float
    last_briefed_at: float


@dataclass
class Change:
    id: int
    watched_id: int
    seen_at: float
    summary: str
    source_quote: str
    source_link: str
    briefed: bool


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
CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY,
    checked_at REAL NOT NULL,
    last_change_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'email',
    password_hash TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

class Memory:
    def __init__(self, path: Path | str = ":memory:", embedder: HashEmbedder | None = None) -> None:
        # One connection per request; never shared across threads without care.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
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

    def token_hits(self, query: str, limit: int = 10) -> list[tuple[Note, int]]:
        """Notes sharing topic tokens with the query, with overlap counts.

        Ranked by distinct shared tokens (more first), ties broken by recency.
        A query with no shared tokens matches nothing, whatever the wording.
        """
        wanted = set(content_tokens(query))
        if not wanted:
            return []
        scored: list[tuple[Note, int]] = []
        for row in self.db.execute("SELECT * FROM notes").fetchall():
            note = self._note_from(row)
            have = set(content_tokens(f"{note.text} {note.text_latin}"))
            overlap = len(wanted & have)
            if overlap:
                scored.append((note, overlap))
        scored.sort(key=lambda pair: (pair[1], pair[0].id), reverse=True)
        return scored[:limit]

    def search_text(self, query: str, limit: int = 10) -> list[Note]:
        """Keyword search over both scripts, most shared tokens first."""
        return [note for note, _ in self.token_hits(query, limit=limit)]

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

    def list_fired(self, limit: int = 20) -> list[Reminder]:
        rows = self.db.execute(
            "SELECT * FROM reminders WHERE armed = 0 ORDER BY fire_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._reminder_from(r) for r in rows]

    def recent_changes(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            "SELECT c.summary, c.source_quote, c.source_link, c.seen_at, c.briefed,"
            " w.url AS watch_url, w.kind AS watch_kind"
            " FROM changes c JOIN watched_items w ON w.id = c.watched_id"
            " ORDER BY c.seen_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

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

    # -- users + sessions -------------------------------------------------
    def create_user(
        self, email: str, name: str = "", avatar_url: str = "",
        provider: str = "email", password_hash: str = "",
    ) -> User:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO users (email, name, avatar_url, provider, password_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (email.strip().lower(), name.strip(), avatar_url, provider, password_hash, now),
        )
        self.db.commit()
        return self.get_user(cur.lastrowid or 0)  # type: ignore[return-value]

    def find_user_by_email(self, email: str) -> User | None:
        row = self.db.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return self._user_from(row) if row else None

    def get_user(self, user_id: int) -> User | None:
        row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from(row) if row else None

    def update_user(self, user_id: int, name: str = "", avatar_url: str = "") -> None:
        if name:
            self.db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        if avatar_url:
            self.db.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, user_id))
        self.db.commit()

    def create_session(self, user_id: int, token_hash: str, ttl_seconds: float) -> None:
        now = time.time()
        self.db.execute(
            "INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, now + ttl_seconds),
        )
        self.db.commit()

    def get_session_user(self, token_hash: str, now: float | None = None) -> User | None:
        row = self.db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash, time.time() if now is None else now),
        ).fetchone()
        return self._user_from(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self.db.commit()

    def delete_user_sessions(self, user_id: int) -> None:
        self.db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.db.commit()

    @staticmethod
    def _user_from(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            avatar_url=row["avatar_url"],
            provider=row["provider"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
        )

    # -- work entries ---------------------------------------------------
    def upsert_work_entry(
        self, persona: str, org: str, issue_ref: str, done: list[str], pending: list[str]
    ) -> WorkEntry:
        existing = self.find_work_entry(org, issue_ref)
        now = time.time()
        if existing is None:
            cur = self.db.execute(
                "INSERT INTO work_entries (persona, org, issue_ref, done_json, pending_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (persona, org, issue_ref, self.dumps(done), self.dumps(pending), now, now),
            )
            self.db.commit()
            return WorkEntry(
                id=cur.lastrowid or 0, persona=persona, org=org, issue_ref=issue_ref,
                done=done, pending=pending, created_at=now, updated_at=now,
            )
        merged_done = existing.done + [d for d in done if d not in existing.done]
        merged_pending = [p for p in existing.pending if p not in done]
        merged_pending += [p for p in pending if p not in merged_pending]
        self.db.execute(
            "UPDATE work_entries SET done_json = ?, pending_json = ?, updated_at = ? WHERE id = ?",
            (self.dumps(merged_done), self.dumps(merged_pending), now, existing.id),
        )
        self.db.commit()
        existing.done, existing.pending, existing.updated_at = merged_done, merged_pending, now
        return existing

    def delete_work_entry(self, entry_id: int) -> bool:
        cur = self.db.execute("DELETE FROM work_entries WHERE id = ?", (entry_id,))
        self.db.commit()
        return cur.rowcount > 0

    def update_work_entry(self, entry_id: int, done: list[str], pending: list[str]) -> WorkEntry:
        now = time.time()
        self.db.execute(
            "UPDATE work_entries SET done_json = ?, pending_json = ?, updated_at = ? WHERE id = ?",
            (self.dumps(done), self.dumps(pending), now, entry_id),
        )
        self.db.commit()
        row = self.db.execute("SELECT * FROM work_entries WHERE id = ?", (entry_id,)).fetchone()
        return self._entry_from(row)

    def find_work_entry(self, org: str = "", issue_ref: str = "") -> WorkEntry | None:
        rows = self.db.execute("SELECT * FROM work_entries ORDER BY updated_at DESC").fetchall()
        for row in rows:
            org_ok = not org or row["org"].lower() == org.lower()
            ref_ok = not issue_ref or row["issue_ref"].lower() == issue_ref.lower()
            if org_ok and ref_ok and (org or issue_ref or (row["org"] == "" and row["issue_ref"] == "")):
                return self._entry_from(row)
        return None

    def list_work_entries(self, persona: str | None = None, limit: int = 20) -> list[WorkEntry]:
        if persona:
            rows = self.db.execute(
                "SELECT * FROM work_entries WHERE persona = ? ORDER BY updated_at DESC LIMIT ?",
                (persona, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM work_entries ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._entry_from(r) for r in rows]

    # -- watched items + changes ------------------------------------------
    def watch_url(self, kind: str, url: str) -> WatchedItem:
        self.db.execute("INSERT OR IGNORE INTO watched_items (kind, url) VALUES (?, ?)", (kind, url))
        self.db.commit()
        row = self.db.execute("SELECT * FROM watched_items WHERE url = ?", (url,)).fetchone()
        return self._watched_from(row)

    def list_watched(self) -> list[WatchedItem]:
        return [self._watched_from(r) for r in self.db.execute("SELECT * FROM watched_items").fetchall()]

    def unwatch(self, watched_id: int) -> bool:
        self.db.execute("DELETE FROM changes WHERE watched_id = ?", (watched_id,))
        cur = self.db.execute("DELETE FROM watched_items WHERE id = ?", (watched_id,))
        self.db.commit()
        return cur.rowcount > 0

    def update_cursor(self, watched_id: int, cursor: str, checked_at: float) -> None:
        self.db.execute(
            "UPDATE watched_items SET cursor = ?, last_checked_at = ? WHERE id = ?",
            (cursor, checked_at, watched_id),
        )
        self.db.commit()

    def touch_briefed(self, watched_id: int, briefed_at: float) -> None:
        self.db.execute(
            "UPDATE watched_items SET last_briefed_at = ? WHERE id = ?", (briefed_at, watched_id)
        )
        self.db.commit()

    def store_changes(self, watched_id: int, changes: list[tuple[str, str, str, float]]) -> None:
        self.db.executemany(
            "INSERT INTO changes (watched_id, summary, source_quote, source_link, seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(watched_id, s, q, link, at) for s, q, link, at in changes],
        )
        self.db.commit()

    def max_change_id(self) -> int:
        """Highest stored change id, 0 when nothing observed yet."""
        row = self.db.execute("SELECT COALESCE(MAX(id), 0) AS m FROM changes").fetchone()
        return row["m"]

    def count_changes_since(self, change_id: int) -> int:
        """Changes stored after the given change id (after a check instance)."""
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM changes WHERE id > ?", (change_id,)
        ).fetchone()
        return row["n"]

    def last_check_id(self) -> int | None:
        """Change id watermark of the most recent check press, None if never."""
        row = self.db.execute(
            "SELECT last_change_id FROM check_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["last_change_id"] if row else None

    def record_check(self, last_change_id: int, checked_at: float) -> None:
        """Store one check press as an instance other presses compare against."""
        self.db.execute(
            "INSERT INTO check_runs (checked_at, last_change_id) VALUES (?, ?)",
            (checked_at, last_change_id),
        )
        self.db.commit()

    def unbriefed_changes(self) -> list[tuple[WatchedItem, list[Change]]]:
        out: list[tuple[WatchedItem, list[Change]]] = []
        for watched in self.list_watched():
            rows = self.db.execute(
                "SELECT * FROM changes WHERE watched_id = ? AND briefed = 0 ORDER BY seen_at",
                (watched.id,),
            ).fetchall()
            if rows:
                out.append((watched, [self._change_from(r) for r in rows]))
        return out

    def mark_changes_briefed(self, change_ids: list[int]) -> None:
        self.db.executemany(
            "UPDATE changes SET briefed = 1 WHERE id = ?", [(i,) for i in change_ids]
        )
        self.db.commit()

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _entry_from(row: sqlite3.Row) -> WorkEntry:
        return WorkEntry(
            id=row["id"],
            persona=row["persona"],
            org=row["org"],
            issue_ref=row["issue_ref"],
            done=json.loads(row["done_json"] or "[]"),
            pending=json.loads(row["pending_json"] or "[]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _watched_from(row: sqlite3.Row) -> WatchedItem:
        return WatchedItem(
            id=row["id"],
            kind=row["kind"],
            url=row["url"],
            cursor=row["cursor"] or "",
            last_checked_at=row["last_checked_at"] or 0,
            last_briefed_at=row["last_briefed_at"] or 0,
        )

    @staticmethod
    def _change_from(row: sqlite3.Row) -> Change:
        return Change(
            id=row["id"],
            watched_id=row["watched_id"],
            seen_at=row["seen_at"],
            summary=row["summary"],
            source_quote=row["source_quote"] or "",
            source_link=row["source_link"] or "",
            briefed=bool(row["briefed"]),
        )

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
