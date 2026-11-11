"""Remo web server: browser mic loop, timeline, briefings, alarms.

Run from the project root:

    uvicorn server:app --host 127.0.0.1 --port 8000

then open http://127.0.0.1:8000 in a browser.
"""
from __future__ import annotations

import json
import os
import re
import wave
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from remo import boost as boost_mod
from remo import brain_keywords as kw
from remo import turn as turn_mod
from remo.capture.audio import downsample_mono16
from remo.config import Settings, load_settings
from remo.log import get_logger
from remo.memory import Memory
from remo.paths import data_dir
from remo import reminders as reminders_mod
from remo.stt import transcribe_file_rest, transcribe_pcm
from remo.tts import synthesize

ROOT = Path(__file__).resolve().parent
LANGS = ("hi-IN", "mr-IN")
_AUDIO_NAME = re.compile(r"^[0-9a-f]{40}\.wav$")

log = get_logger("server")
app = FastAPI(title="Remo")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
app.mount("/landing", StaticFiles(directory=ROOT / "landing", html=True), name="landing")


def get_db_path() -> Path:
    override = os.environ.get("REMO_DB", "")
    return Path(override) if override else data_dir() / "remo.db"


def mem_dep() -> Any:
    mem = Memory(get_db_path())
    try:
        yield mem
    finally:
        mem.close()


def _settings_for(lang: str | None) -> Settings:
    code = lang or "hi-IN"
    if code not in LANGS:
        raise HTTPException(status_code=400, detail=f"unsupported language: {code}")
    return replace(load_settings(), language=code)


class TextTurn(BaseModel):
    text: str
    lang: str | None = None
    pending: dict | None = None
    speak: bool = True


class Speak(BaseModel):
    text: str
    lang: str | None = None


def _audio_url(audio: Path | None) -> str | None:
    return f"/api/audio/{audio.name}" if audio else None


def _turn_payload(result: turn_mod.TurnResult, transcript: str | None = None) -> dict:
    payload: dict[str, Any] = {
        "text": result.text,
        "action": result.action,
        "audio_url": _audio_url(result.audio),
        "pending": result.pending,
        "links": result.links,
    }
    if transcript is not None:
        payload["transcript"] = transcript
    return payload


def _resolve_pending(
    mem: Memory, text: str, pending: dict, settings: Settings, speak: bool
) -> turn_mod.TurnResult | None:
    """Route one message against carried-over pending state (quiz/remind/confirm)."""
    action = (pending or {}).get("action")
    if action == "quiz":
        return turn_mod.answer_quiz(mem, pending, text, settings=settings, speak=speak)
    if action == "remind_ask":
        return turn_mod.complete_remind_task(mem, pending, text, settings=settings, speak=speak)
    if action in ("undo", "forget", "remind"):
        decided = turn_mod.confirm_pending_text(mem, pending, text, settings=settings, speak=speak)
        if decided is None:
            from remo import lang as lang_mod

            ask = lang_mod.strings(settings.language)["ask_yes_no"]
            audio = None
            if speak:
                try:
                    audio = synthesize(ask, settings=settings)
                except Exception as exc:  # noqa: BLE001 - voice-out must never kill the turn
                    log.warning("voice-out failed: %s", exc)
            return turn_mod.TurnResult(text=ask, audio=audio, action="confirm_ask", pending=pending)
        return decided
    return None


def _route_text(
    mem: Memory, text: str, pending: dict | None, settings: Settings, speak: bool = True
) -> turn_mod.TurnResult:
    # A fresh save keyword always wins (it also drops stale pending state).
    if kw.match_save_keyword(text) is not None:
        return turn_mod.handle_text(text, mem=mem, settings=settings, speak=speak)
    if pending:
        resolved = _resolve_pending(mem, text, pending, settings, speak)
        if resolved is not None:
            return resolved
    return turn_mod.handle_text(text, mem=mem, settings=settings, speak=speak)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "landing" / "landing.html")


@app.get("/app", include_in_schema=False)
def webapp() -> FileResponse:
    return FileResponse(ROOT / "web" / "app.html")


@app.post("/api/turn/text")
def turn_text(body: TextTurn, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    settings = _settings_for(body.lang)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    result = _route_text(mem, body.text, body.pending, settings, body.speak)
    return JSONResponse(_turn_payload(result))


@app.post("/api/turn/audio")
def turn_audio(
    file: UploadFile = File(...),
    lang: str = Form("hi-IN"),
    pending: str = Form("{}"),
    speak: str = Form("true"),
    mem: Memory = Depends(mem_dep),  # noqa: B008
) -> JSONResponse:
    """Sync endpoint: the STT stream runs its own loop; blocking I/O throughout."""
    settings = _settings_for(lang)
    voice_out = speak.strip().lower() not in ("false", "0", "no", "off")
    try:
        pending_obj = json.loads(pending) if pending else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="pending must be JSON") from None
    raw = file.file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="audio too large (5 MB max)")
    pcm = _wav_to_pcm16(raw)
    if pcm is None:
        raise HTTPException(status_code=400, detail="expected a 16-bit PCM WAV file")
    boost_words = boost_mod.build_boost_list(mem)
    try:
        heard = transcribe_pcm(pcm, settings=settings, sample_rate=16000, boost_words=boost_words)
        transcript = heard.text
    except Exception as exc:  # noqa: BLE001 - streaming may fail; REST is the fallback
        log.warning("streaming STT failed, trying REST: %s", exc)
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        _write_wav(tmp_path, pcm, 16000)
        try:
            transcript = transcribe_file_rest(tmp_path, settings.language)
        finally:
            tmp_path.unlink(missing_ok=True)
    transcript, _ = boost_mod.apply_fix_rules(transcript, mem.get_fix_rules())
    if not transcript.strip():
        from remo import lang as lang_mod

        ask = lang_mod.strings(settings.language)["prompt_repeat"]
        audio = None
        if voice_out:
            try:
                audio = synthesize(ask, settings=settings)
            except Exception as exc:  # noqa: BLE001 - voice-out must never kill the turn
                log.warning("voice-out failed: %s", exc)
        return JSONResponse(_turn_payload(
            turn_mod.TurnResult(text=ask, audio=audio, action="repeat"), transcript=""
        ))
    result = _route_text(mem, transcript, pending_obj, settings, voice_out)
    return JSONResponse(_turn_payload(result, transcript=transcript))


def _wav_to_pcm16(raw: bytes) -> bytes | None:
    """Accept browser WAV uploads; normalize to 16 kHz mono for Prisma."""
    import io

    try:
        with wave.open(io.BytesIO(raw), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError):
        return None
    if width != 2:
        return None
    if channels == 2:
        import struct

        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        frames = struct.pack(f"<{len(samples) // 2}h", *[(a + b) // 2 for a, b in zip(samples[::2], samples[1::2])])
    elif channels != 1:
        return None
    if rate == 16000:
        return frames
    if rate % 16000 == 0:
        return downsample_mono16(frames, rate, 16000)
    return None


def _write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


@app.get("/api/state")
def state(mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    notes = [
        {"id": n.id, "text": n.text, "created_at": n.created_at, "source": n.source}
        for n in mem.list_recent(30)
    ]
    alarms = [
        {"id": r.id, "text": r.text, "fire_at": r.fire_at,
         "when": datetime.fromtimestamp(r.fire_at).strftime("%d %b, %I:%M %p").lstrip("0")}
        for r in mem.list_armed()
    ]
    entries = [
        {"id": e.id, "persona": e.persona, "org": e.org, "issue_ref": e.issue_ref,
         "done": e.done, "pending": e.pending}
        for e in mem.list_work_entries(limit=10)
    ]
    watched = [{"id": w.id, "url": w.url, "checked_at": w.last_checked_at} for w in mem.list_watched()]
    fired = [
        {"id": r.id, "text": r.text, "fire_at": r.fire_at,
         "when": datetime.fromtimestamp(r.fire_at).strftime("%d %b, %I:%M %p").lstrip("0")}
        for r in mem.list_fired()
    ]
    return JSONResponse({
        "notes": notes, "reminders": alarms, "reminders_fired": fired, "work": entries,
        "watched": watched, "changes": mem.recent_changes(), "learned": boost_mod.snapshot(mem),
    })


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.forget_note(note_id):
        raise HTTPException(status_code=404, detail="no such note")
    return JSONResponse({"deleted": True})


@app.delete("/api/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.delete_reminder(reminder_id):
        raise HTTPException(status_code=404, detail="no such reminder")
    return JSONResponse({"deleted": True})


@app.delete("/api/work/{entry_id}")
def delete_work(entry_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.delete_work_entry(entry_id):
        raise HTTPException(status_code=404, detail="no such work entry")
    return JSONResponse({"deleted": True})


@app.delete("/api/watch/{watched_id}")
def delete_watch(watched_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.unwatch(watched_id):
        raise HTTPException(status_code=404, detail="no such watched item")
    return JSONResponse({"deleted": True})


@app.get("/api/info")
def info() -> JSONResponse:
    from remo import lang as lang_mod
    from remo import __version__ as _version

    settings = load_settings()
    return JSONResponse({
        "version": _version,
        "language": settings.language,
        "voice": lang_mod.resolve_voice(settings.tts_voice, settings.language),
        "stt_model": settings.stt_model,
        "tts_model": settings.tts_model,
    })


@app.get("/api/alarms")
def alarms() -> JSONResponse:
    due = reminders_mod.collect_due(get_db_path())
    return JSONResponse({"alarms": [{"id": r.id, "text": r.text} for r in due]})


@app.post("/api/speak")
def speak(body: Speak) -> JSONResponse:
    settings = _settings_for(body.lang)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    audio = synthesize(body.text, settings=settings)
    return JSONResponse({"audio_url": _audio_url(audio)})


@app.get("/api/audio/{name}")
def audio(name: str) -> FileResponse:
    if not _AUDIO_NAME.match(name):
        raise HTTPException(status_code=404, detail="no such audio")
    path = data_dir() / "tts_cache" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/demo/seed")
def demo_seed(mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    """Synthetic demo data for the video and first-time judges. Fake org, fake notes."""
    import time as _time

    from remo import worklog as worklog_mod

    mem.add_note("maths mein integration ho gaya, differential equations baaki hai", source="demo")
    mem.add_note("kal kirana se atta aur dal lena hai", source="demo")
    worklog_mod.store_update(mem, "org DemoCo issue 12: login fix ho gaya, docs baaki hai")
    mem.add_reminder("chai dekhna", _time.time() + 3600)
    mem.watch_url("github_repo", "https://github.com/python/cpython")
    return JSONResponse({"seeded": True})
