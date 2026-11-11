"""Optional LLM composer (Gemini): natural answers over retrieved notes.

Extractive recall stays the default and the fallback. When GEMINI_API_KEY is
set, generic recall answers are composed by Gemini from the retrieved notes
with a grounded-only prompt; any failure (quota, timeout, bad output) returns
None and the caller falls back to extractive. Only retrieved note snippets are
sent, never the whole memory.
"""
from __future__ import annotations

import requests

from remo import lang as lang_mod
from remo import recall as recall_mod
from remo.config import Settings
from remo.log import get_logger
from remo.memory import Memory, Note

log = get_logger("llm")

DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = 8.0
MAX_CHARS = 600

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
    model: str = DEFAULT_MODEL,
    api_key: str = "",
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """One grounded answer, or None when composing is impossible/failed."""
    if not api_key or not notes or not question.strip():
        return None
    generation_config: dict = {"temperature": 0.2, "maxOutputTokens": 300}
    if "2.5" in model:
        # 2.5 models think by default and burn the output budget on it;
        # a composer needs the answer, not the reasoning trace.
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM.format(lang=_LANG_NAME.get(lang, _LANG_NAME["hi"]))}]},
        "contents": [{"parts": [{"text": _prompt(question, notes[:3], context)}]}],
        "generationConfig": generation_config,
    }
    try:
        resp = requests.post(f"{_URL.format(model=model)}?key={api_key}", json=body, timeout=timeout)
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except Exception as exc:  # noqa: BLE001 - every failure means "fall back to extractive"
        log.debug("compose failed, falling back to extractive: %s", exc)
        return None
    if not text:
        return None
    return text[:MAX_CHARS].rstrip()


def try_compose(question: str, notes: list[Note], mem: Memory, settings: Settings) -> str | None:
    """Compose over retrieved notes when a key is configured, else None."""
    if not settings.gemini_api_key or not notes:
        return None
    context = recall_mod.describe_note(notes[0], mem)
    return compose(
        question,
        [n.text for n in notes[:3]],
        context=context,
        lang=lang_mod.lang_key(settings.language),
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
    )
