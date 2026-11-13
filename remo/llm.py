"""Optional LLM composer (Gemini): natural answers over retrieved notes.

Extractive recall stays the default and the fallback. When GEMINI_API_KEY is
set, generic recall answers are composed by Gemini from the retrieved notes
with a grounded-only prompt; any failure (quota, timeout, bad output) returns
None and the caller falls back to extractive. Only retrieved note snippets are
sent, never the whole memory.
"""
from __future__ import annotations

import base64
import json
import re

import requests

from remo import lang as lang_mod
from remo import recall as recall_mod
from remo.config import Settings
from remo.log import get_logger
from remo.memory import Change, Memory, Note, WatchedItem, WorkEntry

log = get_logger("llm")

DEFAULT_MODELS = ("gemini-2.5-flash", "gemini-3-flash-preview")
TIMEOUT_SECONDS = 8.0
MAX_CHARS = 600
_RETRYABLE = {429, 500, 502, 503, 504}

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_LANG_NAME = {"hi": "Hinglish (Hindi-English mix, Devanagari script is fine)", "mr": "Marathi"}

_SYSTEM = (
    "You answer questions about the user's own notes. Use ONLY the notes below. "
    "Answer from them as far as they go; if something is missing, first say what "
    "the notes do say, then add what is missing in one short sentence. "
    "Reply in {lang}: 2-3 short spoken sentences, no quotes, no lists, "
    "no 'you said' framing."
)


def _prompt(question: str, notes: list[str], context: str) -> str:
    lines = [f"Question: {question}", "Notes:"]
    lines += [f"{i}. {note}" for i, note in enumerate(notes, 1)]
    if context:
        lines.append(f"Context: {context}")
    lines.append("Answer:")
    return "\n".join(lines)


def compose(
    question: str,
    notes: list[str],
    *,
    context: str = "",
    lang: str = "hi",
    model: str = "",
    models: list[str] | None = None,
    api_key: str = "",
    api_keys: list[str] | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """One grounded answer, or None when composing is impossible/failed."""
    keys = api_keys or ([api_key] if api_key else [])
    if not keys or not notes or not question.strip():
        return None
    text = _generate(
        [{"text": _prompt(question, notes[:3], context)}],
        _SYSTEM.format(lang=_LANG_NAME.get(lang, _LANG_NAME["hi"])),
        models=models or ([model] if model else list(DEFAULT_MODELS)),
        api_keys=keys, timeout=timeout, max_tokens=300, json_mode=False,
    )
    if not text:
        return None
    return text[:MAX_CHARS].rstrip()


INTENTS = ("save", "recall", "forget", "remind", "quiz", "briefing", "add_task", "other")

_INTENT_SYSTEM = (
    "You route one voice-assistant transcript to an intent. The user speaks Hinglish, English, "
    "Marathi, or Hindi, in Latin or Devanagari script. Reply with JSON ONLY, no other text: "
    '{"intent": "<one of save, recall, forget, remind, quiz, briefing, add_task, other>", ...slots}. '
    "save: the user wants to store information for later, in any phrasing "
    "(remember, yaad rakhna, note kar lo, ...). Put the content WITHOUT the command words in "
    '"save_text". '
    "recall: the user asks about stored information (what is left, kya bacha, batao, where was I, "
    '...). Put the question in "query". '
    "forget: the user wants to delete a memory (bhool jao, bhula do, forget, delete, ...). Put what "
    'to forget in "target", or "last" for the last thing said. '
    "remind: the user wants a reminder (yaad dilana, remind me, ...). Put the task in "
    '"remind_task" and the time in their own words in "remind_when" (empty string if missing). '
    "quiz: the user wants to be quizzed (quiz karo, test lo, ...). Put the topic in "
    '"quiz_topic" (empty string if none). '
    "briefing: the user wants a plan, briefing, or catch-up (plan, welcome back, briefing, ...). "
    "add_task: the user wants to add a to-do task (add task, ...). Put the task in "
    '"task_text". '
    "other: greetings, chit-chat, or anything else. Put a short reply in "
    '"reply", 1-2 sentences in the user\'s language. NEVER invent memories, notes, tasks, or '
    "appointments; if asked about those, say you do not remember any."
)


def _parse_json_object(text: str) -> dict | None:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _thinking_cap(model: str) -> dict | None:
    if "2.5" in model:
        return {"thinkingBudget": 0}
    if re.search(r"\b3(\.\d+)?\b", model):
        return {"thinkingLevel": "MINIMAL"}
    return None


def _generate(parts: list[dict], system: str, *, models: list[str], api_keys: list[str],
              timeout: float, max_tokens: int, json_mode: bool) -> str | None:
    """Try each key, and each model per key; quota/server/timeout moves along."""
    for key in api_keys:
        for model in models:
            generation_config: dict = {"temperature": 0.2 if not json_mode else 0.0,
                                       "maxOutputTokens": max_tokens}
            cap = _thinking_cap(model)
            if cap:
                generation_config["thinkingConfig"] = cap
            if json_mode:
                generation_config["response_mime_type"] = "application/json"
            body = {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": parts}],
                "generationConfig": generation_config,
            }
            try:
                resp = requests.post(f"{_URL.format(model=model)}?key={key}", json=body,
                                     timeout=timeout)
                resp.raise_for_status()
                out = resp.json()["candidates"][0]["content"]["parts"]
                text = "".join(part.get("text", "") for part in out).strip()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                log.debug("model %s failed with %s", model, status)
                if status == 403:
                    break  # bad key: other models on it will fail the same way
                if status in _RETRYABLE:
                    continue
                return None
            except (requests.Timeout, requests.ConnectionError) as exc:
                log.debug("model %s unreachable: %s", model, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - malformed reply: try the next model
                log.debug("model %s gave a bad reply: %s", model, exc)
                continue
            if text:
                return text
    return None


def parse_intent(transcript: str, *, model: str = "", models: list[str] | None = None,
                 api_key: str = "", api_keys: list[str] | None = None,
                 timeout: float = TIMEOUT_SECONDS) -> dict | None:
    """One transcript into {intent, slots}, or None when unparseable/failed."""
    keys = api_keys or ([api_key] if api_key else [])
    if not keys or not transcript.strip():
        return None
    raw = _generate([{"text": f"Transcript: {transcript.strip()}"}], _INTENT_SYSTEM,
                    models=models or ([model] if model else list(DEFAULT_MODELS)),
                    api_keys=keys, timeout=timeout, max_tokens=300, json_mode=True)
    if raw is None:
        return None
    parsed = _parse_json_object(raw)
    if parsed is None or parsed.get("intent") not in INTENTS:
        return None
    return parsed


def try_intent(text: str, settings: Settings) -> dict | None:
    """Parse when a key is configured, else None (patterns take over)."""
    if not settings.gemini_api_keys:
        return None
    return parse_intent(text, models=list(settings.gemini_models), api_keys=list(settings.gemini_api_keys))


_BRIEF_SYSTEM = (
    "You speak a welcome-back briefing for a voice assistant. Pending work first, then what is "
    "new out there. Reply in {lang}: 3-5 short spoken sentences, warm and direct, no quotes, "
    "no lists, no URLs (links travel separately, never speak them)."
)


def compose_briefing(pending: list[str], changes: list[str], *, lang: str = "hi",
                     model: str = "", models: list[str] | None = None, api_key: str = "",
                     api_keys: list[str] | None = None,
                     timeout: float = TIMEOUT_SECONDS) -> str | None:
    """A spoken welcome-back over pending work + fresh changes, or None on failure."""
    keys = api_keys or ([api_key] if api_key else [])
    if not keys or (not pending and not changes):
        return None
    lines = ["Pending work:"]
    lines += [f"- {p}" for p in pending[:6]]
    lines += ["New changes out there:"]
    lines += [f"- {c}" for c in changes[:6]]
    lines.append("Briefing:")
    text = _generate(
        [{"text": "\n".join(lines)}],
        _BRIEF_SYSTEM.format(lang=_LANG_NAME.get(lang, _LANG_NAME["hi"])),
        models=models or ([model] if model else list(DEFAULT_MODELS)),
        api_keys=keys, timeout=timeout, max_tokens=400, json_mode=False,
    )
    if not text:
        return None
    return text[:MAX_CHARS].rstrip()


def try_briefing(entries: list[WorkEntry], deltas: list[tuple[WatchedItem, list[Change]]],
                 settings: Settings) -> str | None:
    """Brief when a key is configured and there is anything to say, else None."""
    if not settings.gemini_api_keys:
        return None
    pending = [p for entry in entries for p in entry.pending[:3]]
    changes = [c.summary for _, items in deltas for c in items]
    if not pending and not changes:
        return None
    return compose_briefing(pending, changes, lang=lang_mod.lang_key(settings.language),
                            models=list(settings.gemini_models), api_keys=list(settings.gemini_api_keys))


PDF_MAX_NOTES = 12
PDF_NOTE_CHARS = 140

_PDF_PROMPT = (
    "Read this document ({filename}) and write up to {limit} short study notes, one per line, "
    "plain text, no numbering, no bullets, no quotes. Each note states one fact in under "
    "{chars} characters, in the document's own language (Hinglish or Marathi written as-is is fine)."
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•\d]+[.)\]]?\s+)")


def _clean_note_line(line: str) -> str:
    return _BULLET_RE.sub("", line).strip().strip("'\"").strip()


def extract_pdf_notes(pdf_bytes: bytes, *, filename: str = "document.pdf",
                      model: str = "", models: list[str] | None = None, api_key: str = "",
                      timeout: float = 60.0, settings: Settings | None = None) -> list[str] | None:
    """Ask Gemini to read a PDF and propose short notes; None on any failure."""
    keys = list(settings.gemini_api_keys) if settings else ([api_key] if api_key else [])
    resolved_models = models or ([model] if model else
                                 (list(settings.gemini_models) if settings else list(DEFAULT_MODELS)))
    if not keys or not pdf_bytes:
        return None
    file_part = {"inline_data": {"mime_type": "application/pdf",
                                 "data": base64.b64encode(pdf_bytes).decode()}}
    text = _generate(
        [file_part, {"text": _PDF_PROMPT.format(
            filename=filename or "document.pdf", limit=PDF_MAX_NOTES, chars=PDF_NOTE_CHARS)}],
        "You turn documents into short spoken-study notes.",
        models=resolved_models,
        api_keys=keys, timeout=timeout, max_tokens=1200, json_mode=False,
    )
    if not text:
        return None
    notes = []
    for line in text.splitlines():
        cleaned = _clean_note_line(line)
        if cleaned:
            notes.append(cleaned[:PDF_NOTE_CHARS].rstrip())
    return notes[:PDF_MAX_NOTES] or None


def try_compose(question: str, notes: list[Note], mem: Memory, settings: Settings) -> str | None:
    """Compose over retrieved notes when a key is configured, else None."""
    if not settings.gemini_api_keys or not notes:
        return None
    context = recall_mod.describe_note(notes[0], mem)
    return compose(
        question,
        [n.text for n in notes[:3]],
        context=context,
        lang=lang_mod.lang_key(settings.language),
        models=list(settings.gemini_models),
        api_keys=list(settings.gemini_api_keys),
    )
