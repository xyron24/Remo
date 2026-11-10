"""One voice turn: transcript in, spoken reply out.

Routes through the keyword gate first (auto-save), then undo/forget guards,
then left-off and recall answering. Stateless: confirmations travel back as a
`pending` payload the caller holds and resolves with `confirm_pending`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from remo import brain_keywords as kw
from remo import recall as recall_mod
from remo.config import Settings, load_settings
from remo.log import get_logger
from remo.memory import Memory
from remo.tts import synthesize

log = get_logger("turn")

HELP = (
    "Kuch yaad karwane ke liye 'yaad rakhna' se shuru karo. "
    "Puchhne ke liye bas bol do, jaise 'kya bacha hai?'"
)
NOTHING_NAMED = "Is naam se kuch yaad nahi hai."
UNDONE = "Bhula diya."
KEPT = "Rehne diya, yaad rahega."


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

    if recall_mod.is_left_off_query(text):
        say = recall_mod.compose_left_off(mem.list_recent(20))
        return _speak(say, "left_off", settings, speak)

    hits = recall_mod.hybrid_search(mem, text, limit=3)
    if recall_mod.is_recall_query(text) or hits:
        return _speak(recall_mod.compose_recall(hits), "recall", settings, speak)
    return _speak(HELP, "help", settings, speak)


def confirm_pending(
    mem: Memory, pending: dict | None, yes: bool, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Resolve an undo/forget confirmation carried from a previous turn."""
    settings = settings or load_settings()
    if not yes:
        return _speak(KEPT, "kept", settings, speak)
    action = (pending or {}).get("action")
    if action == "undo":
        forgotten = mem.forget_last_note()
        say = UNDONE if forgotten else NOTHING_NAMED
        return _speak(say, "undone", settings, speak)
    if action == "forget":
        ok = mem.forget_note(int((pending or {}).get("note_id", -1)))
        return _speak(UNDONE if ok else NOTHING_NAMED, "forgot", settings, speak)
    return _speak(HELP, "help", settings, speak)
