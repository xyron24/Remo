"""Optional LLM composer (Gemini): natural answers over retrieved notes.

Extractive recall stays the default and the fallback. When GEMINI_API_KEY is
set, generic recall answers are composed by Gemini from the retrieved notes
with a grounded-only prompt; any failure (quota, timeout, bad output) returns
None and the caller falls back to extractive. Only retrieved note snippets are
sent, never the whole memory.
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
import re
import threading
import time

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

_PERSONA = (
    "You are Remo, a male assistant. Always use masculine Hindi grammar about yourself "
    "(kar sakta hoon, gaya tha, dunga, karunga), never feminine forms. "
)

_SYSTEM = (
    _PERSONA
    + "You answer questions about the user's own notes. Use ONLY the notes below. "
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
    _PERSONA
    + "You route one voice-assistant transcript to an intent. The user speaks Hinglish, English, "
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
    "For recall, also fill \"reply\" with the FULL user-facing answer composed from the context "
    "below (2-4 short spoken sentences in the user's language, no quotes, no lists); leave it "
    "empty only when the context cannot answer the question. "
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


_tls = threading.local()
_COOLDOWNS: dict[tuple[str, str], float] = {}
_LAST_OK: dict[tuple[str, str], float] = {}
_RETRY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)
_HEALTH_PATH: str | None = None
_HEALTH_LOCK = threading.Lock()
_HEALTH_LOADED = False


def _http() -> requests.Session:
    """One keep-alive session per thread: no fresh TLS handshake per call."""
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        _tls.session = sess
    return sess


def _cool_key(key: str, model: str) -> tuple[str, str]:
    return (hashlib.sha256(key.encode()).hexdigest()[:16], model)


def configure_health(path: str | None) -> None:
    """Point health persistence at PATH (tests); None restores the default file."""
    global _HEALTH_PATH, _HEALTH_LOADED
    with _HEALTH_LOCK:
        _HEALTH_PATH = path
        _HEALTH_LOADED = False


def _health_file() -> str:
    if _HEALTH_PATH is not None:
        return _HEALTH_PATH
    from remo.paths import data_dir

    return str(data_dir() / "llm_health.json")


def _load_health() -> None:
    """Cooldowns survive restarts; a redeploy must not re-probe dead pools."""
    global _HEALTH_LOADED
    with _HEALTH_LOCK:
        if _HEALTH_LOADED:
            return
        _HEALTH_LOADED = True
        try:
            with open(_health_file(), encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
    now = time.time()
    for combo, until in (saved.get("cooldowns") or {}).items():
        try:
            key_hash, model = combo.split(" ", 1)
            if float(until) > now:
                _COOLDOWNS[(key_hash, model)] = float(until)
        except (ValueError, TypeError, AttributeError):
            continue
    for combo, stamp in (saved.get("last_ok") or {}).items():
        try:
            key_hash, model = combo.split(" ", 1)
            _LAST_OK[(key_hash, model)] = float(stamp)
        except (ValueError, TypeError, AttributeError):
            continue


def _save_health() -> None:
    with _HEALTH_LOCK:
        payload = {
            "cooldowns": {f"{k} {m}": u for (k, m), u in _COOLDOWNS.items()},
            "last_ok": {f"{k} {m}": t for (k, m), t in _LAST_OK.items()},
        }
        try:
            with open(_health_file(), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except OSError:
            pass


def _cooldown_seconds(exc: Exception, status: int = 0) -> float:
    match = _RETRY_RE.search(str(exc))
    if match:
        try:
            return min(float(match.group(1)) + 1.0, 300.0)
        except ValueError:
            pass
    if status == 429:
        return 600.0  # quota pools recover in minutes-to-hours, not seconds
    return 60.0


HEDGE_AFTER_SECONDS = 2.5
HEDGE_MAX_RACING = 2


class _Next(Exception):
    """Try the next combination."""


class _CoolCombo(_Next):
    def __init__(self, combo: tuple[str, str], seconds: float) -> None:
        super().__init__(str(combo))
        self.combo = combo
        self.seconds = seconds


class _SkipKey(_Next):
    def __init__(self, key: str) -> None:
        super().__init__("bad key")
        self.key = key


class _Fatal(Exception):
    """Do not try anything else."""


def _attempt(key: str, model: str, parts: list[dict], system: str, timeout: float,
             max_tokens: int, json_mode: bool) -> str:
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
        resp = _http().post(f"{_URL.format(model=model)}?key={key}", json=body, timeout=timeout)
        resp.raise_for_status()
        out = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in out).strip()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        log.debug("model %s failed with %s", model, status)
        if status == 403:
            raise _SkipKey(key) from exc
        if status in _RETRYABLE:
            raise _CoolCombo(_cool_key(key, model), _cooldown_seconds(exc, status)) from exc
        raise _Fatal() from exc
    except (requests.Timeout, requests.ConnectionError) as exc:
        log.debug("model %s unreachable: %s", model, exc)
        raise _CoolCombo(_cool_key(key, model), 60.0) from exc
    except (_Next, _Fatal):
        raise
    except Exception as exc:  # noqa: BLE001 - malformed reply: try the next model
        log.debug("model %s gave a bad reply: %s", model, exc)
        raise _Next() from exc


def _generate(parts: list[dict], system: str, *, models: list[str], api_keys: list[str],
              timeout: float, max_tokens: int, json_mode: bool) -> str | None:
    """Race combinations: first success wins; a slow call never blocks the next.

    Cooling combos are skipped outright, so an all-dead pool fails fast.
    Extra combinations race only while earlier ones are still slow.
    """
    _load_health()
    now = time.time()
    combos = [(key, model) for key in api_keys for model in models]
    combos.sort(key=lambda c: (now < _COOLDOWNS.get(_cool_key(*c), 0),
                               -_LAST_OK.get(_cool_key(*c), 0)))
    combos = [c for c in combos if time.time() >= _COOLDOWNS.get(_cool_key(*c), 0)]
    if not combos:
        return None
    dead_keys: set[str] = set()
    pending: dict[concurrent.futures.Future, tuple[str, str]] = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=HEDGE_MAX_RACING,
                                                 thread_name_prefix="llm-hedge")
    try:
        index = 0

        def launch() -> None:
            nonlocal index
            while index < len(combos) and len(pending) < HEDGE_MAX_RACING:
                combo = combos[index]
                index += 1
                if combo[0] in dead_keys:
                    continue
                key, model = combo
                pending[pool.submit(_attempt, key, model, parts, system, timeout,
                                    max_tokens, json_mode)] = combo
                return

        launch()
        while pending:
            done, _ = concurrent.futures.wait(pending, timeout=HEDGE_AFTER_SECONDS,
                                              return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                combo = pending.pop(future)
                try:
                    text = future.result()
                except _SkipKey as skipped:
                    dead_keys.add(skipped.key)
                    launch()
                except _CoolCombo as cooled:
                    _COOLDOWNS[cooled.combo] = time.time() + cooled.seconds
                    _save_health()
                    launch()
                except _Next:
                    launch()
                except _Fatal:
                    return None
                else:
                    if text:
                        _LAST_OK[_cool_key(*combo)] = time.time()
                        return text
                    launch()
            if not done:
                launch()  # nothing finished in time: race the next combination
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def parse_intent(transcript: str, *, context: str = "", model: str = "",
                 models: list[str] | None = None, api_key: str = "",
                 api_keys: list[str] | None = None,
                 timeout: float = TIMEOUT_SECONDS) -> dict | None:
    """One transcript into {intent, slots}, or None when unparseable/failed."""
    keys = api_keys or ([api_key] if api_key else [])
    if not keys or not transcript.strip():
        return None
    prompt = f"Transcript: {transcript.strip()}"
    if context.strip():
        prompt += f"\nContext (memories, tasks, reminders):\n{context.strip()}"
    raw = _generate([{"text": prompt}], _INTENT_SYSTEM,
                    models=models or ([model] if model else list(DEFAULT_MODELS)),
                    api_keys=keys, timeout=timeout, max_tokens=400, json_mode=True)
    if raw is None:
        return None
    parsed = _parse_json_object(raw)
    if parsed is None or parsed.get("intent") not in INTENTS:
        return None
    return parsed


_ROMANIZE_SYSTEM = (
    "Rewrite this Hinglish, Hindi, or Marathi question in Latin (Roman) script, keeping English "
    "words in their English spelling. Reply with ONLY the rewritten question, no quotes, "
    "no explanation."
)


def romanize_query(text: str, settings: Settings, timeout: float = TIMEOUT_SECONDS) -> str | None:
    """Romanize a no-match query so Latin-script notes can match; None on failure."""
    if not settings.gemini_api_keys or not text.strip():
        return None
    out = _generate(
        [{"text": text.strip()}],
        _ROMANIZE_SYSTEM,
        models=list(settings.gemini_models),
        api_keys=list(settings.gemini_api_keys),
        timeout=timeout, max_tokens=100, json_mode=False,
    )
    if not out:
        return None
    return out.strip().strip("'\"").strip() or None


def search_with_romanize(mem: Memory, query: str, settings: Settings,
                         limit: int = 3) -> list[Note]:
    """Token search, plus a romanized retry when nothing matches (cross-script)."""
    hits = recall_mod.hybrid_search(mem, query, limit=limit)
    if hits or not settings.gemini_api_keys:
        return hits
    latin = romanize_query(query, settings)
    if not latin or latin.strip() == query.strip():
        return hits
    return recall_mod.hybrid_search(mem, latin, limit=limit)


def recall_context(mem: Memory, text: str, settings: Settings | None = None) -> str:
    """Local retrieval first: recent + matching notes, tasks, reminders."""
    seen: set[int] = set()
    notes: list[str] = []
    matched = (search_with_romanize(mem, text, settings, limit=5)
               if settings is not None else recall_mod.hybrid_search(mem, text, limit=5))
    for note in mem.list_recent(5) + matched:
        if note.id not in seen:
            seen.add(note.id)
            notes.append(note.text[:120])
    tasks = [p[:100] for e in mem.list_work_entries(limit=5) for p in e.pending[:2]]
    rems = [r.text[:100] for r in mem.list_armed()[:3]]
    lines = ["Recent/matching memories:"]
    lines += [f"- {n}" for n in notes[:10]] or ["- (none)"]
    lines += ["Open tasks:"]
    lines += [f"- {t}" for t in tasks[:5]] or ["- (none)"]
    lines += ["Armed reminders:"]
    lines += [f"- {r}" for r in rems[:3]] or ["- (none)"]
    return "\n".join(lines)


def try_intent(text: str, mem: Memory, settings: Settings) -> dict | None:
    """Parse when a key is configured, else None (patterns take over)."""
    if not settings.gemini_api_keys:
        return None
    return parse_intent(text, context=recall_context(mem, text, settings),
                        models=list(settings.gemini_models),
                        api_keys=list(settings.gemini_api_keys))


_BRIEF_SYSTEM = (
    _PERSONA
    + "You speak a welcome-back briefing for a voice assistant. Pending work first, then what is "
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


_LEFT_OFF_SYSTEM = (
    _PERSONA
    + "You speak a 'what is left' answer for a voice assistant. State what is pending from the "
    "memories first, then remaining tasks with their count, then armed reminders with their "
    "count. Reply in {lang}: short spoken sentences, warm and direct, no quotes, no lists."
)


def compose_left_off_full(pending_notes: list[str], tasks: list[str], rems: list[str], *,
                          lang: str = "hi", model: str = "",
                          models: list[str] | None = None, api_key: str = "",
                          api_keys: list[str] | None = None,
                          timeout: float = TIMEOUT_SECONDS) -> str | None:
    """One natural what's-left answer over memories, tasks, and reminders."""
    keys = api_keys or ([api_key] if api_key else [])
    if not keys or (not pending_notes and not tasks and not rems):
        return None
    lines = ["Pending memories:"]
    lines += [f"- {p}" for p in pending_notes[:4]]
    lines += ["Remaining tasks:"]
    lines += [f"- {t}" for t in tasks[:4]]
    lines += ["Armed reminders:"]
    lines += [f"- {r}" for r in rems[:4]]
    lines.append("Answer:")
    text = _generate(
        [{"text": "\n".join(lines)}],
        _LEFT_OFF_SYSTEM.format(lang=_LANG_NAME.get(lang, _LANG_NAME["hi"])),
        models=models or ([model] if model else list(DEFAULT_MODELS)),
        api_keys=keys, timeout=timeout, max_tokens=400, json_mode=False,
    )
    if not text:
        return None
    return text[:MAX_CHARS].rstrip()


def try_left_off(notes: list[Note], tasks: list[str], rems: list[str],
                 settings: Settings) -> str | None:
    """Compose what's-left when a key is configured, else None (template takes over)."""
    if not settings.gemini_api_keys:
        return None
    pending = [n.text for n in notes if recall_mod.is_pending_note(n)][:4]
    if not pending and not tasks and not rems:
        return None
    return compose_left_off_full(
        pending, [t for t in tasks if t.strip()][:4], [r for r in rems if r.strip()][:4],
        lang=lang_mod.lang_key(settings.language),
        models=list(settings.gemini_models), api_keys=list(settings.gemini_api_keys),
    )


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
