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

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from remo import auth as auth_mod
from remo import boost as boost_mod
from remo import brain_keywords as kw
from remo import llm as llm_mod
from remo import turn as turn_mod
from remo.capture.audio import downsample_mono16
from remo.config import Settings, load_settings
from remo.log import get_logger
from remo.memory import Memory, User
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


def _session_user(request: Request, mem: Memory) -> User | None:
    token = request.cookies.get(auth_mod.SESSION_COOKIE, "")
    if not token:
        return None
    return mem.get_session_user(auth_mod.hash_token(token))


def current_user(request: Request, mem: Memory = Depends(mem_dep)) -> User:  # noqa: B008
    user = _session_user(request, mem)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "provider": user.provider,
        "created_at": user.created_at,
    }


def _start_session(mem: Memory, user: User, secure: bool) -> str:
    token = auth_mod.new_session_token()
    mem.create_session(user.id, auth_mod.hash_token(token), auth_mod.SESSION_TTL_SECONDS)
    return token


def _set_session_cookie(response: JSONResponse | RedirectResponse, token: str, secure: bool) -> None:
    response.set_cookie(auth_mod.SESSION_COOKIE, token, **auth_mod.session_cookie_kwargs(secure))


@app.get("/login", include_in_schema=False)
def login_page(request: Request, mem: Memory = Depends(mem_dep)):  # noqa: B008
    if _session_user(request, mem) is not None:
        return RedirectResponse("/app", status_code=302)
    return FileResponse(ROOT / "web" / "login.html")


@app.get("/app", include_in_schema=False)
def webapp(request: Request, mem: Memory = Depends(mem_dep)):  # noqa: B008
    if _session_user(request, mem) is None:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(ROOT / "web" / "app.html")


class Register(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""


class Login(BaseModel):
    email: str = ""
    password: str = ""


@app.post("/api/auth/register")
def auth_register(body: Register, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    settings = load_settings()
    email = body.email.strip().lower()
    if not auth_mod.valid_email(email):
        raise HTTPException(status_code=400, detail="enter a valid email address")
    if not auth_mod.valid_password(body.password):
        raise HTTPException(status_code=400, detail="password needs at least 8 characters")
    if mem.find_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="that email is already registered; sign in instead")
    import sqlite3

    try:
        user = mem.create_user(
            email,
            name=body.name.strip() or email.split("@")[0],
            password_hash=auth_mod.hash_password(body.password),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="that email is already registered; sign in instead") from None
    # Registered, not signed in: the client returns to the login form.
    return JSONResponse({"user": _user_payload(user)})


@app.post("/api/auth/login")
def auth_login(body: Login, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    settings = load_settings()
    user = mem.find_user_by_email(body.email)
    if user is None or not user.password_hash or not auth_mod.check_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="wrong email or password")
    token = _start_session(mem, user, settings.cookie_secure)
    response = JSONResponse({"user": _user_payload(user)})
    _set_session_cookie(response, token, settings.cookie_secure)
    return response


@app.post("/api/logout")
def auth_logout(request: Request, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    token = request.cookies.get(auth_mod.SESSION_COOKIE, "")
    if token:
        mem.delete_session(auth_mod.hash_token(token))
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth_mod.SESSION_COOKIE, path="/")
    return response


@app.get("/api/me")
def auth_me(user: User = Depends(current_user)) -> JSONResponse:
    return JSONResponse({"user": _user_payload(user)})


@app.get("/api/auth/providers")
def auth_providers() -> JSONResponse:
    settings = load_settings()
    return JSONResponse({"google": bool(settings.google_client_id and settings.google_client_secret)})


def _oauth_redirect_uri(request: Request) -> str:
    settings = load_settings()
    base = settings.public_url or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/google/callback"


@app.get("/api/auth/google/start")
def google_start(request: Request) -> RedirectResponse:
    settings = load_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse("/login?error=not_configured", status_code=302)
    state = auth_mod.new_oauth_state()
    url = auth_mod.google_auth_url(settings.google_client_id, _oauth_redirect_uri(request), state)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        auth_mod.OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax",
        secure=settings.cookie_secure, max_age=600, path="/",
    )
    return response


@app.get("/api/auth/google/callback")
def google_callback(request: Request, mem: Memory = Depends(mem_dep)) -> RedirectResponse:  # noqa: B008
    settings = load_settings()
    params = request.query_params
    if params.get("error"):
        return RedirectResponse("/login?error=cancelled", status_code=302)
    state, want = params.get("state", ""), request.cookies.get(auth_mod.OAUTH_STATE_COOKIE, "")
    if not state or not want or state != want:
        return RedirectResponse("/login?error=expired", status_code=302)
    code = params.get("code", "")
    try:
        access = auth_mod.google_exchange_code(
            settings.google_client_id, settings.google_client_secret, code, _oauth_redirect_uri(request)
        )
        profile = auth_mod.google_userinfo(access)
    except Exception as exc:  # noqa: BLE001 - provider failures become a login retry
        log.warning("google sign-in failed: %s", exc)
        return RedirectResponse("/login?error=failed", status_code=302)
    email = str(profile.get("email", "")).strip().lower()
    if not email or not profile.get("email_verified"):
        return RedirectResponse("/login?error=unverified", status_code=302)
    user = mem.find_user_by_email(email)
    if user is None:
        user = mem.create_user(
            email, name=str(profile.get("name", "") or email.split("@")[0]),
            avatar_url=str(profile.get("picture", "")), provider="google",
        )
    else:
        mem.update_user(user.id, name=user.name or str(profile.get("name", "")),
                        avatar_url=user.avatar_url or str(profile.get("picture", "")))
    token = _start_session(mem, user, settings.cookie_secure)
    response = RedirectResponse("/app", status_code=302)
    _set_session_cookie(response, token, settings.cookie_secure)
    response.delete_cookie(auth_mod.OAUTH_STATE_COOKIE, path="/")
    return response


@app.post("/api/turn/text", dependencies=[Depends(current_user)])
def turn_text(body: TextTurn, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    settings = _settings_for(body.lang)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    result = _route_text(mem, body.text, body.pending, settings, body.speak)
    return JSONResponse(_turn_payload(result))


@app.post("/api/turn/audio", dependencies=[Depends(current_user)])
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


@app.get("/api/state", dependencies=[Depends(current_user)])
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


@app.delete("/api/notes/{note_id}", dependencies=[Depends(current_user)])
def delete_note(note_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.forget_note(note_id):
        raise HTTPException(status_code=404, detail="no such note")
    return JSONResponse({"deleted": True})


@app.delete("/api/reminders/{reminder_id}", dependencies=[Depends(current_user)])
def delete_reminder(reminder_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.delete_reminder(reminder_id):
        raise HTTPException(status_code=404, detail="no such reminder")
    return JSONResponse({"deleted": True})


@app.delete("/api/work/{entry_id}", dependencies=[Depends(current_user)])
def delete_work(entry_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.delete_work_entry(entry_id):
        raise HTTPException(status_code=404, detail="no such work entry")
    return JSONResponse({"deleted": True})


@app.delete("/api/watch/{watched_id}", dependencies=[Depends(current_user)])
def delete_watch(watched_id: int, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    if not mem.unwatch(watched_id):
        raise HTTPException(status_code=404, detail="no such watched item")
    return JSONResponse({"deleted": True})


@app.get("/api/info", dependencies=[Depends(current_user)])
def info() -> JSONResponse:
    from remo import lang as lang_mod
    from remo import __version__ as _version

    settings = load_settings()
    return JSONResponse({
        "version": _version,
        "language": settings.language,
        "voice": lang_mod.resolve_voice(settings.tts_voice, settings.language),
        "voices": {code: lang_mod.resolve_voice(settings.tts_voice, code) for code in ("hi-IN", "mr-IN")},
        "stt_model": settings.stt_model,
        "tts_model": settings.tts_model,
    })


@app.get("/api/alarms", dependencies=[Depends(current_user)])
def alarms() -> JSONResponse:
    due = reminders_mod.collect_due(get_db_path())
    return JSONResponse({"alarms": [{"id": r.id, "text": r.text} for r in due]})


@app.post("/api/speak", dependencies=[Depends(current_user)])
def speak(body: Speak) -> JSONResponse:
    settings = _settings_for(body.lang)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    audio = synthesize(body.text, settings=settings)
    return JSONResponse({"audio_url": _audio_url(audio)})


@app.get("/api/audio/{name}", dependencies=[Depends(current_user)])
def audio(name: str) -> FileResponse:
    if not _AUDIO_NAME.match(name):
        raise HTTPException(status_code=404, detail="no such audio")
    path = data_dir() / "tts_cache" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/wav")


class ImportKeep(BaseModel):
    notes: list[str] = []
    source: str = ""


@app.post("/api/import/pdf", dependencies=[Depends(current_user)])
def import_pdf(file: UploadFile = File(...)) -> JSONResponse:
    """Gemini reads a PDF and proposes short notes; the user ticks what to keep."""
    settings = load_settings()
    name = (file.filename or "").strip() or "document.pdf"
    raw = file.file.read()
    if not name.lower().endswith(".pdf") or not raw.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="upload a real .pdf file")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF too large (10 MB max)")
    if not settings.gemini_api_keys:
        raise HTTPException(status_code=503, detail="set GEMINI_API_KEY to import PDFs")
    notes = llm_mod.extract_pdf_notes(raw, filename=name, settings=settings)
    if not notes:
        raise HTTPException(status_code=502, detail="could not read that PDF; try another")
    return JSONResponse({"filename": name, "notes": notes})


@app.post("/api/import/keep", dependencies=[Depends(current_user)])
def import_keep(body: ImportKeep, mem: Memory = Depends(mem_dep)) -> JSONResponse:  # noqa: B008
    cleaned = [n.strip()[:500] for n in body.notes if n.strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="tick at least one note")
    source = f"pdf:{(body.source or 'document.pdf').strip()}"[:40]
    for note in cleaned[:20]:
        mem.add_note(note, source=source)
    return JSONResponse({"saved": min(len(cleaned), 20)})


@app.post("/api/demo/seed", dependencies=[Depends(current_user)])
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
