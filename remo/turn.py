"""One voice turn: transcript in, spoken reply out.

Routes through the keyword gate first (auto-save), then undo/forget guards,
then left-off and recall answering. Stateless: confirmations travel back as a
`pending` payload the caller holds and resolves with `confirm_pending`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from remo import brain_keywords as kw
from remo import recall as recall_mod
from remo.answers import parse_yes_no
from remo import briefing as briefing_mod
from remo.config import Settings, load_settings
from remo.log import get_logger
from remo.memory import Memory
from remo import quiz as quiz_mod
from remo import reminders as reminders_mod
from remo.tts import synthesize

log = get_logger("turn")

HELP = (
    "Kuch yaad karwane ke liye 'yaad rakhna' se shuru karo. "
    "Puchhne ke liye bas bol do, jaise 'kya bacha hai?'"
)
NOTHING_NAMED = "Is naam se kuch yaad nahi hai."
UNDONE = "Bhula diya."
KEPT = "Rehne diya, yaad rahega."
ASK_WHEN = "Kab yaad dilaun? Waqt samajh nahi aaya."
ASK_TASK = "Kis liye yaad dilaun?"
ASK_YES_NO = "Haan ya nahi?"
REMINDERS_OFF = "Theek hai, reminder nahi lagaya."

_REMIND_MARKERS = ("yaad dilana", "yaad dila", "remind me", "reminder lagao", "reminder")


@dataclass
class TurnResult:
    text: str
    audio: Path | None
    action: str
    pending: dict | None = field(default=None)


def _speak(text: str, action: str, settings: Settings, speak: bool, pending: dict | None = None) -> TurnResult:
    audio: Path | None = None
    if speak:
        try:
            audio = synthesize(text, settings=settings)
        except Exception as exc:  # noqa: BLE001 - voice-out must never kill the turn
            log.warning("voice-out failed, answering in text only: %s", exc)
    return TurnResult(text=text, audio=audio, action=action, pending=pending)


def handle_text(text: str, *, mem: Memory, settings: Settings | None = None, speak: bool = True) -> TurnResult:
    """Run one transcript through save/recall/forget routing + voice-out."""
    settings = settings or load_settings()

    content = kw.match_save_keyword(text)
    if content is not None:
        reason = kw.check_content(content)
        if reason:
            return _speak(kw.PROMPT_REPEAT_HI, "repeat", settings, speak)
        mem.add_note(content)
        return _speak(kw.ACK_SAVED_HI, "saved", settings, speak)

    if kw.is_undo_last(text):
        return _speak(kw.CONFIRM_UNDO_HI, "undo_ask", settings, speak, pending={"action": "undo"})

    target = kw.match_forget(text)
    if target is not None:
        hits = recall_mod.hybrid_search(mem, target, limit=3)
        if not hits:
            return _speak(NOTHING_NAMED, "recall", settings, speak)
        return _speak(
            f"'{hits[0].text}' — bhula doon?",
            "forget_ask",
            settings,
            speak,
            pending={"action": "forget", "note_id": hits[0].id},
        )

    if _is_remind_request(text):
        return _remind_turn(text, mem=mem, settings=settings, speak=speak)

    if briefing_mod.is_plan_query(text):
        return _speak(briefing_mod.compose_plan(mem), "plan", settings, speak)

    if quiz_mod.is_quiz_request(text):
        topic = _quiz_topic(text)
        session, say = quiz_mod.start_quiz(mem, topic=topic)
        pending = {"action": "quiz", "session": session.to_dict()} if session else None
        return _speak(say, "quiz_ask", settings, speak, pending=pending)

    if recall_mod.is_left_off_query(text):
        say = recall_mod.compose_left_off(mem.list_recent(20))
        return _speak(say, "left_off", settings, speak)

    hits = recall_mod.hybrid_search(mem, text, limit=3)
    if recall_mod.is_recall_query(text) or hits:
        return _speak(recall_mod.compose_recall(hits), "recall", settings, speak)
    return _speak(HELP, "help", settings, speak)


def _is_remind_request(text: str) -> bool:
    norm = kw.normalize(text)
    return any(marker in norm for marker in _REMIND_MARKERS)


def _quiz_topic(text: str) -> str | None:
    """"maths mein quiz karo" -> "maths mein"; None for a general quiz."""
    norm = kw.normalize(text)
    for marker in quiz_mod.QUIZ_MARKERS:
        if marker in norm:
            topic = norm.replace(marker, "").strip(" .,!?-")
            return topic or None
    return None


def _remind_turn(text: str, *, mem: Memory, settings: Settings, speak: bool) -> TurnResult:
    task, moment = reminders_mod.split_task_time(text, datetime.now())
    if moment is None:
        return _speak(ASK_WHEN, "help", settings, speak)
    if not task:
        pending = {"action": "remind_ask", "fire_at": moment.timestamp()}
        return _speak(ASK_TASK, "remind_ask", settings, speak, pending=pending)
    readback = reminders_mod.format_readback(moment, datetime.now())
    pending = {"action": "remind", "text": task, "fire_at": moment.timestamp()}
    return _speak(f"{readback}: {task}. Pakka?", "remind_confirm", settings, speak, pending=pending)


def complete_remind_task(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Arm a reminder whose task arrived one turn after its time."""
    settings = settings or load_settings()
    task = kw.normalize(text).strip(" .,!?;:")
    if not task:
        return _speak(ASK_TASK, "remind_ask", settings, speak, pending=pending)
    fire_at = float((pending or {}).get("fire_at", 0))
    mem.add_reminder(text.strip(), fire_at)
    readback = reminders_mod.format_readback(datetime.fromtimestamp(fire_at), datetime.now())
    return _speak(f"Ho gaya: {readback} — {text.strip()}.", "reminded", settings, speak)


def answer_quiz(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Score one quiz answer carried in a pending quiz session."""
    settings = settings or load_settings()
    session = quiz_mod.QuizSession.from_dict((pending or {}).get("session", {}))
    if not session.note_ids:
        return _speak(HELP, "help", settings, speak)
    session, say, done = quiz_mod.answer_question(mem, session, text)
    next_pending = None if done else {"action": "quiz", "session": session.to_dict()}
    return _speak(say, "quiz_done" if done else "quiz_ask", settings, speak, pending=next_pending)


def confirm_pending(
    mem: Memory, pending: dict | None, yes: bool, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Resolve an undo/forget/remind confirmation carried from a previous turn."""
    settings = settings or load_settings()
    action = (pending or {}).get("action")
    if not yes:
        say = REMINDERS_OFF if action == "remind" else KEPT
        return _speak(say, "kept", settings, speak)
    if action == "undo":
        forgotten = mem.forget_last_note()
        say = UNDONE if forgotten else NOTHING_NAMED
        return _speak(say, "undone", settings, speak)
    if action == "forget":
        ok = mem.forget_note(int((pending or {}).get("note_id", -1)))
        return _speak(UNDONE if ok else NOTHING_NAMED, "forgot", settings, speak)
    if action == "remind":
        data = pending or {}
        mem.add_reminder(str(data.get("text", "")), float(data.get("fire_at", 0)))
        return _speak("Ho gaya, waqt par yaad dila dunga.", "reminded", settings, speak)
    return _speak(HELP, "help", settings, speak)


def confirm_pending_text(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult | None:
    """Spoken yes/no over a pending confirm; None means ask "Haan ya nahi?" again."""
    settings = settings or load_settings()
    verdict = parse_yes_no(text)
    if verdict is None:
        return None
    return confirm_pending(mem, pending, verdict, settings=settings, speak=speak)
