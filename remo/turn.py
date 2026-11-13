"""One voice turn: transcript in, spoken reply out.

Routes through the keyword gate first (auto-save), then undo/forget guards,
then reminders, plan, quiz, watching, and recall answering. Stateless:
confirmations travel back as a `pending` payload the caller holds and resolves.
Every reply renders in the locale from settings (Hinglish/Marathi).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from remo import brain_keywords as kw
from remo import recall as recall_mod
from remo.answers import parse_yes_no
from remo import briefing as briefing_mod
from remo.config import Settings, load_settings
from remo import lang as lang_mod
from remo import llm as llm_mod
from remo.log import get_logger
from remo.memory import Memory
from remo import quiz as quiz_mod
from remo import reminders as reminders_mod
from remo.tts import synthesize
from remo import watcher as watcher_mod
from remo import worklog as worklog_mod

log = get_logger("turn")

_REMIND_MARKERS = ("yaad dilana", "yaad dila", "remind me", "reminder lagao", "reminder", "aathvan",
                   "utha dena", "utha do", "jaga dena", "jaga do", "alarm lagao", "alarm laga do")

_WATCH_MARKERS = ("watch karo", "track karo", "nazar rakho", "watch this", "laksh thev", "watchlist")

_UPDATE_MARKERS = ("koi update", "update aaya", "update aaye", "check update", "naya kya hai", "what changed",
                   "what's new", "koi badlaav", "kahi update", "kay badal")

_WELCOME_MARKERS = ("welcome back", "vapas aaya", "wapas aaya", "wapis aaya", "vapas aa gaya", "main vapas")

_DEVA_MARKERS = {
    "remind": ("रिमाइंड",),
    "watch": ("वॉच", "ट्रैक", "नजर", "लक्ष", "वॉचलिस्ट"),
    "update": ("अपडेट",),
    "welcome": ("वेलकम",),
}

_WORD_MARKERS = {
    # Singles that mean the intent alone ("reminder" -> ask when/what).
    # Bare verbs like "dilana"/"track" stay out: "paise dilana" is not a reminder.
    "remind": frozenset({"reminder"}),
    "watch": frozenset({"watch"}),
    "update": frozenset({"update"}),
    "welcome": frozenset({"welcome"}),
}


def _marker_hit(text: str, phrases: tuple[str, ...], kind: str) -> bool:
    """Intent phrases in either script: raw, folded-both-sides, token, Devanagari."""
    from remo.memory import content_tokens, fold_text

    norm = kw.normalize(text)
    if any(marker in norm for marker in phrases):
        return True
    if any(marker in norm for marker in _DEVA_MARKERS[kind]):
        return True
    folded = fold_text(text)
    if any(fold_text(marker) in folded for marker in phrases):
        return True
    return not set(content_tokens(text)).isdisjoint(_WORD_MARKERS[kind])


@dataclass
class TurnResult:
    text: str
    audio: Path | None
    action: str
    pending: dict | None = field(default=None)
    links: list[str] = field(default_factory=list)


def _speak(
    text: str,
    action: str,
    settings: Settings,
    speak: bool,
    pending: dict | None = None,
    links: list[str] | None = None,
) -> TurnResult:
    audio: Path | None = None
    if speak:
        try:
            audio = synthesize(text, settings=settings)
        except Exception as exc:  # noqa: BLE001 - voice-out must never kill the turn
            log.warning("voice-out failed, answering in text only: %s", exc)
    return TurnResult(text=text, audio=audio, action=action, pending=pending, links=links or [])


def handle_text(text: str, *, mem: Memory, settings: Settings | None = None, speak: bool = True) -> TurnResult:
    """The LLM understands every turn; patterns cover URLs and no-key fallback."""
    settings = settings or load_settings()
    s = lang_mod.strings(settings.language)

    if settings.gemini_api_keys:
        decided = _llm_turn(text, mem=mem, settings=settings, speak=speak, s=s)
        if decided is not None:
            return decided
    return _pattern_turn(text, mem=mem, settings=settings, speak=speak, s=s)


def _llm_turn(text: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult | None:
    """Understand anything via the LLM; None means fall through to patterns."""
    # URL extraction stays exact: regex never mangles links the way a model might.
    if _marker_hit(text, _WATCH_MARKERS, "watch"):
        return _watch_turn(text, mem=mem, settings=settings, speak=speak, s=s)
    if _marker_hit(text, _UPDATE_MARKERS, "update"):
        return check_updates(mem=mem, settings=settings, speak=speak)
    if _marker_hit(text, _WELCOME_MARKERS, "welcome"):
        return _welcome_turn(mem=mem, settings=settings, speak=speak, s=s)
    parsed = llm_mod.try_intent(text, mem, settings)
    if not parsed:
        return None
    kind = parsed.get("intent", "other")

    if kind == "save":
        content = (parsed.get("save_text") or "").strip()
        if not content or kw.check_content(content):
            return None
        return _save_content(content, mem, settings, speak, s, warm=True)

    if kind == "recall":
        reply = (parsed.get("reply") or "").strip()
        if reply:
            return _speak(reply[:600], "recall", settings, speak)
        query = (parsed.get("query") or "").strip() or text
        result = _recall_turn(query, mem=mem, settings=settings, speak=speak, s=s)
        return result if result.action != "help" else None

    if kind == "forget":
        target = (parsed.get("target") or "").strip()
        if target.lower() in ("last", "last one", "aakhri", "आखिरी"):
            return _speak(s["confirm_undo"], "undo_ask", settings, speak, pending={"action": "undo"})
        hits = recall_mod.hybrid_search(mem, target or text, limit=3)
        if not hits:
            return _speak(s["nothing_named"], "recall", settings, speak)
        return _speak(
            s["forget_ask"].format(text=hits[0].text),
            "forget_ask",
            settings,
            speak,
            pending={"action": "forget", "note_id": hits[0].id},
        )

    if kind == "remind":
        combined = f"{parsed.get('remind_task', '')} {parsed.get('remind_when', '')}".strip()
        return _remind_turn(combined or text, mem=mem, settings=settings, speak=speak, s=s)

    if kind == "quiz":
        topic = (parsed.get("quiz_topic") or "").strip() or None
        session, say = quiz_mod.start_quiz(mem, topic=topic)
        pending = {"action": "quiz", "session": session.to_dict()} if session else None
        return _speak(say, "quiz_ask", settings, speak, pending=pending)

    if kind == "briefing":
        return _speak(briefing_mod.compose_plan(mem, s=s), "plan", settings, speak)

    if kind == "add_task":
        task = (parsed.get("task_text") or "").strip()
        if not task:
            return _speak(s["task_ask"], "task_ask", settings, speak)
        return _add_task(task, mem=mem, settings=settings, speak=speak, s=s)

    reply = (parsed.get("reply") or "").strip()
    if not reply:
        return None
    return _speak(reply[:600], "chat", settings, speak)


def _save_content(content: str, mem: Memory, settings: Settings, speak: bool, s: dict,
                  warm: bool = False) -> TurnResult:
    mem.add_note(content)
    if worklog_mod.is_work_update(content):
        worklog_mod.store_update(mem, content)
    armed_span = _maybe_auto_remind(mem, content)
    if armed_span:
        return _speak(s["auto_remind"].format(span=armed_span), "saved", settings, speak)
    if worklog_mod.is_work_update(content):
        return _speak(s["ack_saved_work"], "saved", settings, speak)
    ack = s["ack_saved_warm"] if warm else s["ack_saved"]
    return _speak(ack, "saved", settings, speak)


def _add_task(task: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    """A task is a note plus a pending item on the general work entry."""
    mem.add_note(task[:500])
    mem.upsert_work_entry(worklog_mod.detect_persona(task), "", "", [], [task[:200]])
    return _speak(s["task_added"].format(task=task[:120]), "task_added", settings, speak)


def _welcome_turn(mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    entries = mem.list_work_entries(limit=10)
    deltas = mem.unbriefed_changes()
    links = [c.source_link for _, changes in deltas for c in changes if c.source_link]
    say = llm_mod.try_briefing(entries, deltas, settings)
    if say is None:
        say, _ = worklog_mod.compose_welcome_back(entries, deltas, s=s)
    _mark_deltas_briefed(mem, deltas)
    return _speak(say, "welcome", settings, speak, links=links)


def _recall_turn(text: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    """Day plan, left-off, or general recall over one question."""
    day_plan = briefing_mod.wants_day_plan(text)
    if day_plan is not None:
        return _speak(briefing_mod.compose_day_plan(mem, day_plan, s=s), "plan", settings, speak)

    if recall_mod.is_left_off_query(text):
        org, ref = worklog_mod.detect_refs(text)
        if org or ref:
            entry = mem.find_work_entry(org, ref)
            if entry is None:
                return _speak(s["no_work_record"], "left_off", settings, speak)
            return _speak(worklog_mod.compose_entry(entry, s=s), "left_off", settings, speak)
        notes = mem.list_recent(20)
        tasks = [p for e in mem.list_work_entries(limit=10) for p in e.pending[:3]]
        now = datetime.now()
        rems = [
            f"{r.text} ({reminders_mod.format_readback(datetime.fromtimestamp(r.fire_at), now)})"
            for r in mem.list_armed()[:5]
        ]
        say = llm_mod.try_left_off(notes, tasks, rems, settings)
        if say is None:
            say = recall_mod.compose_left_off(notes, s=s, tasks=tasks, reminders=rems)
        return _speak(say, "left_off", settings, speak)

    hits = recall_mod.hybrid_search(mem, text, limit=3)
    if recall_mod.is_recall_query(text) or hits:
        if not hits and recall_mod.is_tell_all_query(text):
            recent = mem.list_recent(3)
            return _speak(recall_mod.compose_recall(recent, s=s), "recall", settings, speak)
        say = llm_mod.try_compose(text, hits, mem, settings) if hits else None
        if say is None:
            say = recall_mod.compose_answer(hits, mem, s=s)
        return _speak(say, "recall", settings, speak)
    return _speak(s["help"], "help", settings, speak)


def _pattern_turn(text: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    """Fast offline routing; also the fallback when the LLM is off or unsure."""
    content = kw.match_save_keyword(text)
    if content is not None:
        reason = kw.check_content(content)
        if reason:
            return _speak(s["prompt_repeat"], "repeat", settings, speak)
        return _save_content(content, mem, settings, speak, s)

    if kw.is_undo_last(text):
        return _speak(s["confirm_undo"], "undo_ask", settings, speak, pending={"action": "undo"})

    target = kw.match_forget(text)
    if target is not None:
        hits = recall_mod.hybrid_search(mem, target, limit=3)
        if not hits:
            return _speak(s["nothing_named"], "recall", settings, speak)
        return _speak(
            s["forget_ask"].format(text=hits[0].text),
            "forget_ask",
            settings,
            speak,
            pending={"action": "forget", "note_id": hits[0].id},
        )

    task = kw.match_task(text)
    if task is not None:
        if not task.strip():
            return _speak(s["task_ask"], "task_ask", settings, speak)
        return _add_task(task.strip(), mem=mem, settings=settings, speak=speak, s=s)

    if _is_remind_request(text):
        return _remind_turn(text, mem=mem, settings=settings, speak=speak, s=s)

    if briefing_mod.is_plan_query(text):
        day = briefing_mod.plan_day(text)
        if day is None:
            return _speak(briefing_mod.compose_plan(mem, s=s), "plan", settings, speak)
        return _speak(briefing_mod.compose_day_plan(mem, day, s=s), "plan", settings, speak)

    if quiz_mod.is_quiz_request(text):
        topic = _quiz_topic(text)
        session, say = quiz_mod.start_quiz(mem, topic=topic)
        pending = {"action": "quiz", "session": session.to_dict()} if session else None
        return _speak(say, "quiz_ask", settings, speak, pending=pending)

    if _marker_hit(text, _WATCH_MARKERS, "watch"):
        return _watch_turn(text, mem=mem, settings=settings, speak=speak, s=s)

    if _marker_hit(text, _UPDATE_MARKERS, "update"):
        return check_updates(mem=mem, settings=settings, speak=speak)

    if _marker_hit(text, _WELCOME_MARKERS, "welcome"):
        return _welcome_turn(mem=mem, settings=settings, speak=speak, s=s)

    return _recall_turn(text, mem=mem, settings=settings, speak=speak, s=s)


def _is_remind_request(text: str) -> bool:
    return _marker_hit(text, _REMIND_MARKERS, "remind")


def _maybe_auto_remind(mem: Memory, content: str) -> str:
    """Arm a reminder the note itself asks for ("... 2 din baad yaad dila dena").

    Returns the time span as said (for the ack), or "" when the note carries
    no reminder instruction. The ack always echoes the time, so a misheard
    time is heard and can be cancelled immediately.
    """
    if not any(marker in kw.normalize(content) for marker in _REMIND_MARKERS):
        return ""
    span, moment = reminders_mod.extract_time_mention(content)
    if moment is None:
        return ""
    task, _ = reminders_mod.split_task_time(content)
    mem.add_reminder((task or content)[:160], moment.timestamp())
    return span.strip()


def _quiz_topic(text: str) -> str | None:
    """"maths mein quiz karo" -> "maths mein"; None for a general quiz."""
    norm = kw.normalize(text)
    for marker in quiz_mod.QUIZ_MARKERS:
        if marker in norm:
            topic = norm.replace(marker, "").strip(" .,!?-")
            return topic or None
    return None


def _remind_turn(text: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    task, moment = reminders_mod.split_task_time(text, datetime.now())
    if moment is None:
        return _speak(s["ask_when"], "help", settings, speak)
    if not task:
        pending = {"action": "remind_ask", "fire_at": moment.timestamp()}
        return _speak(s["ask_task"], "remind_ask", settings, speak, pending=pending)
    readback = reminders_mod.format_readback(moment, datetime.now())
    pending = {"action": "remind", "text": task, "fire_at": moment.timestamp()}
    return _speak(s["remind_confirm"].format(readback=readback, task=task), "remind_confirm",
                  settings, speak, pending=pending)


def complete_remind_task(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Arm a reminder whose task arrived one turn after its time."""
    settings = settings or load_settings()
    s = lang_mod.strings(settings.language)
    task = kw.normalize(text).strip(" .,!?;:")
    if not task:
        return _speak(s["ask_task"], "remind_ask", settings, speak, pending=pending)
    fire_at = float((pending or {}).get("fire_at", 0))
    mem.add_reminder(text.strip(), fire_at)
    readback = reminders_mod.format_readback(datetime.fromtimestamp(fire_at), datetime.now())
    return _speak(s["remind_armed"].format(readback=readback, task=text.strip()), "reminded", settings, speak)


def _watch_turn(text: str, *, mem: Memory, settings: Settings, speak: bool, s: dict) -> TurnResult:
    match = re.search(r"https?://\S+", text)
    url = match.group(0).rstrip(".,!?:;") if match else ""
    kind = watcher_mod.kind_for_url(url) if url else None
    if not kind:
        return _speak(s["bad_watch_url"], "help", settings, speak)
    mem.watch_url(kind, url)
    return _speak(s["watching_ok"], "watching", settings, speak)


def _mark_deltas_briefed(mem: Memory, deltas) -> None:
    ids = [c.id for _, changes in deltas for c in changes]
    if ids:
        mem.mark_changes_briefed(ids)
    for watched, _ in deltas:
        mem.touch_briefed(watched.id, time.time())


def check_updates(
    mem: Memory, *, settings: Settings | None = None, speak: bool = True, fetch=None
) -> TurnResult:
    """Poll watched sources now, then brief only what is new."""
    settings = settings or load_settings()
    s = lang_mod.strings(settings.language)
    if not mem.list_watched():
        return _speak(s["nothing_watched"], "help", settings, speak)
    report = watcher_mod.poll_all(mem, token=settings.github_token, fetch=fetch,
                                  lang=lang_mod.lang_key(settings.language))
    deltas = mem.unbriefed_changes()
    label = datetime.fromtimestamp(report.checked_at).strftime("%I:%M %p").lstrip("0")
    say, links = watcher_mod.compose_updates(deltas, f"as of {label}", s=s)
    if report.errors and not deltas:
        say = s["updates_offline_alone"] + say
    elif report.errors:
        say += s["updates_offline_partial"]
    _mark_deltas_briefed(mem, deltas)
    return _speak(say, "updates", settings, speak, links=links)


def answer_quiz(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Score one quiz answer carried in a pending quiz session."""
    settings = settings or load_settings()
    s = lang_mod.strings(settings.language)
    session = quiz_mod.QuizSession.from_dict((pending or {}).get("session", {}))
    if not session.note_ids:
        return _speak(s["help"], "help", settings, speak)
    session, say, done = quiz_mod.answer_question(mem, session, text)
    next_pending = None if done else {"action": "quiz", "session": session.to_dict()}
    return _speak(say, "quiz_done" if done else "quiz_ask", settings, speak, pending=next_pending)


def confirm_pending(
    mem: Memory, pending: dict | None, yes: bool, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult:
    """Resolve an undo/forget/remind confirmation carried from a previous turn."""
    settings = settings or load_settings()
    s = lang_mod.strings(settings.language)
    action = (pending or {}).get("action")
    if not yes:
        say = s["reminders_off"] if action == "remind" else s["kept"]
        return _speak(say, "kept", settings, speak)
    if action == "undo":
        forgotten = mem.forget_last_note()
        say = s["undone"] if forgotten else s["nothing_named"]
        return _speak(say, "undone", settings, speak)
    if action == "forget":
        ok = mem.forget_note(int((pending or {}).get("note_id", -1)))
        return _speak(s["undone"] if ok else s["nothing_named"], "forgot", settings, speak)
    if action == "remind":
        data = pending or {}
        mem.add_reminder(str(data.get("text", "")), float(data.get("fire_at", 0)))
        return _speak(s["remind_done"], "reminded", settings, speak)
    return _speak(s["help"], "help", settings, speak)


def confirm_pending_text(
    mem: Memory, pending: dict | None, text: str, *, settings: Settings | None = None, speak: bool = True
) -> TurnResult | None:
    """Spoken yes/no over a pending confirm; None means ask again."""
    settings = settings or load_settings()
    verdict = parse_yes_no(text)
    if verdict is None:
        return None
    return confirm_pending(mem, pending, verdict, settings=settings, speak=speak)
