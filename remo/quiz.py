"""Voice quiz: fill-in-the-blank questions from your own notes.

Extractive by design , the blanked word comes from the note itself, and spoken
answers pass on an exact hit or close meaning overlap. Say "bas" to stop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from remo import recall as recall_mod
from remo.brain_keywords import normalize
from remo.memory import HashEmbedder, Memory, Note, cosine

STOPWORDS = frozenset(
    "ke ki ka ko mein me main ne se par aur yaar bhi to hi tha thi the thaye gaya gayi gaye hua hue hui "
    "hai hain hoon ho raha rahi rahe tha the this that with from for and are was were will mere mera meri apne aap "
    "bahut bahot bohot zyada kaafi fir phir abhi ab jab tab kya kab kaun "
    "haan han nahi nahin ji haanji hanji okay theek thik pakka".split()
)

STOP = frozenset({"bas", "stop", "ruk jao", "rukjo", "band karo", "quit", "khatm karo", "rehn de", "rehne de"})

QUIZ_MARKERS = ("quiz karo", "quiz shuru", "quiz start", "mera test lo", "test lo", "sawal pucho", "sawaal")

PASS_SCORE = 0.5
MAX_QUESTIONS = 3


@dataclass
class QuizSession:
    note_ids: list[int]
    current: int = 0
    score: int = 0
    blank: str = ""
    total: int = MAX_QUESTIONS

    def to_dict(self) -> dict:
        return {
            "note_ids": self.note_ids,
            "current": self.current,
            "score": self.score,
            "blank": self.blank,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QuizSession:
        return cls(
            note_ids=list(data.get("note_ids", [])),
            current=int(data.get("current", 0)),
            score=int(data.get("score", 0)),
            blank=str(data.get("blank", "")),
            total=int(data.get("total", MAX_QUESTIONS)),
        )


def is_quiz_request(text: str) -> bool:
    return any(marker in normalize(text) for marker in QUIZ_MARKERS)


def is_stop(text: str) -> bool:
    return normalize(text) in STOP


def make_blank(note_text: str) -> tuple[str, str] | None:
    """Blank the longest meaningful word; returns (question, answer)."""
    words = [w for w in re.findall(r"[A-Za-z\u0900-\u097F']+", note_text) if len(w) >= 4]
    candidates = [w for w in words if w.lower() not in STOPWORDS]
    if not candidates:
        return None
    answer = max(candidates, key=len)
    question = re.sub(re.escape(answer), "___", note_text, count=1)
    return f"Complete karo: {question}", answer


def start_quiz(mem: Memory, topic: str | None = None, total: int = MAX_QUESTIONS) -> tuple[QuizSession | None, str]:
    """Pick notes (optionally on a topic) and ask the first question."""
    pool = recall_mod.hybrid_search(mem, topic, limit=10) if topic else mem.list_recent(10)
    picked: list[Note] = []
    for note in pool:
        if make_blank(note.text) and note.id not in {n.id for n in picked}:
            picked.append(note)
        if len(picked) >= total:
            break
    if not picked:
        return None, "Quiz ke liye notes kam hain. Pehle kuch yaad karwao."
    session = QuizSession(note_ids=[n.id for n in picked], total=len(picked))
    return _ask(mem, session)


def _ask(mem: Memory, session: QuizSession) -> tuple[QuizSession, str]:
    note = mem.get_note(session.note_ids[session.current])
    made = make_blank(note.text) if note else None
    if made is None:  # note vanished mid-quiz; skip it
        session.current += 1
        if session.current >= len(session.note_ids):
            return session, _finale(session)
        return _ask(mem, session)
    question, session.blank = made
    return session, f"Sawal {session.current + 1}: {question}"


def judge(expected: str, said: str, embedder: HashEmbedder | None = None) -> float:
    """0..1 score: exact word hit short-circuits, else meaning overlap."""
    if expected.lower() in said.lower():
        return 1.0
    embedder = embedder or HashEmbedder()
    meaning = cosine(embedder.embed(expected), embedder.embed(said))
    want = set(re.findall(r"\w+", expected.lower()))
    got = set(re.findall(r"\w+", said.lower()))
    overlap = len(want & got) / max(1, len(want))
    return max(meaning, overlap)


def answer_question(
    mem: Memory, session: QuizSession, said: str, embedder: HashEmbedder | None = None
) -> tuple[QuizSession, str, bool]:
    """Score one spoken answer; returns (session, reply, done)."""
    if is_stop(said):
        return session, f"Quiz rok diya. Score: {session.score}/{session.current}.", True
    correct = judge(session.blank, said, embedder) >= PASS_SCORE
    session.score += 1 if correct else 0
    verdict = "Sahi jawab!" if correct else f"Kareeb! Sahi tha: {session.blank}."
    session.current += 1
    if session.current >= len(session.note_ids):
        return session, f"{verdict} {_finale(session)}", True
    session, question = _ask(mem, session)
    return session, f"{verdict} {question}", False


def _finale(session: QuizSession) -> str:
    return f"Quiz khatm! Score: {session.score}/{len(session.note_ids)}."
