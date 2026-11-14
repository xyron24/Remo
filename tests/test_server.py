"""Server: turn routing, state, alarms, audio guard, seeding (all faked)."""
import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server as server_mod
from remo.stt import TranscriptionResult


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REMO_DB", str(tmp_path / "remo.db"))
    monkeypatch.setenv("REMO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.setenv("GNANI_TTS_MODEL", "timbre-v2.5")
    monkeypatch.setenv("GNANI_TTS_VOICE", "")

    def fake_synth(text, settings=None, **kwargs):
        from remo.paths import data_dir

        out = data_dir() / "tts_cache" / ("f" * 40 + ".wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * 3200)
        return out

    monkeypatch.setattr(server_mod, "synthesize", fake_synth)
    monkeypatch.setattr("remo.turn.synthesize", fake_synth)
    logged_in = TestClient(server_mod.app)
    registered = logged_in.post(
        "/api/auth/register",
        json={"name": "Test", "email": "test@example.com", "password": "password-1"},
    )
    assert registered.status_code == 200
    logged = logged_in.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password-1"},
    )
    assert logged.status_code == 200
    return logged_in


def _wav16k(seconds: float = 0.5) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00" * int(16000 * seconds) * 2)
    return buf.getvalue()


def test_index_and_landing_serve(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "landing.css" in home.text
    app = client.get("/app")
    assert app.status_code == 200
    assert "/static/js/app.js" in app.text
    assert client.get("/landing/landing.html").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/js/api.js").status_code == 200
    assert client.get("/static/js/voice.js").status_code == 200


def test_info_reports_version_and_models(client: TestClient) -> None:
    body = client.get("/api/info").json()
    assert body["version"] == "0.1.0"
    assert body["stt_model"] == "prisma-v2.5"
    assert body["tts_model"] == "timbre-v2.5"
    assert body["voice"] == "Nalini"


def test_state_includes_fired_and_changes(client: TestClient, tmp_path: Path) -> None:
    import os
    import time

    from remo.memory import Memory

    mem = Memory(Path(os.environ["REMO_DB"]))
    mem.add_reminder("purana", time.time() - 10)
    for reminder in mem.list_armed(time.time()):
        mem.disarm(reminder.id)
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/1")
    mem.store_changes(watched.id, [("Naya comment.", "q", "https://x/1", time.time())])
    mem.close()
    body = client.get("/api/state").json()
    assert [r["text"] for r in body["reminders_fired"]] == ["purana"]
    assert [c["summary"] for c in body["changes"]] == ["Naya comment."]
    assert body["changes"][0]["watch_url"] == "https://github.com/o/r/issues/1"


def test_text_turn_speak_false_returns_text_only(client: TestClient) -> None:
    body = client.post("/api/turn/text", json={"text": "yaad rakhna chai pini hai", "speak": False}).json()
    assert body["action"] == "saved" and "Yaad kar liya" in body["text"]
    assert body["audio_url"] is None
    spoken = client.post("/api/turn/text", json={"text": "yaad rakhna chai pini hai"}).json()
    assert spoken["audio_url"]


def test_delete_endpoints_remove_each_kind(client: TestClient, tmp_path: Path) -> None:
    import os

    from remo.memory import Memory

    mem = Memory(Path(os.environ["REMO_DB"]))
    note = mem.add_note("temporary")
    reminder = mem.add_reminder("temporary", 9999999999.0)
    entry = mem.upsert_work_entry("student", "", "", [], ["x"])
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/9")
    mem.close()
    assert client.delete(f"/api/notes/{note.id}").json() == {"deleted": True}
    assert client.delete(f"/api/reminders/{reminder.id}").json() == {"deleted": True}
    assert client.delete(f"/api/work/{entry.id}").json() == {"deleted": True}
    assert client.delete(f"/api/watch/{watched.id}").json() == {"deleted": True}
    assert client.get("/api/state").json()["notes"] == []
    assert client.delete("/api/notes/4242").status_code == 404
    assert client.delete("/api/reminders/4242").status_code == 404
    assert client.delete("/api/work/4242").status_code == 404
    assert client.delete("/api/watch/4242").status_code == 404


def test_text_save_then_recall(client: TestClient) -> None:
    saved = client.post("/api/turn/text", json={"text": "yaad rakhna chai pini hai"}).json()
    assert saved["action"] == "saved" and saved["audio_url"]
    assert client.get(saved["audio_url"]).status_code == 200
    asked = client.post("/api/turn/text", json={"text": "kya yaad hai?"}).json()
    assert "chai" in asked["text"]


def test_marathi_turn(client: TestClient) -> None:
    saved = client.post("/api/turn/text", json={"text": "lakshat thev, chai pyaychi aahe", "lang": "mr-IN"}).json()
    assert saved["text"] == "Lakshat thevla."
    bad = client.post("/api/turn/text", json={"text": "hi", "lang": "xx-YY"})
    assert bad.status_code == 400


def test_pending_confirm_flow(client: TestClient) -> None:
    client.post("/api/turn/text", json={"text": "yaad rakhna pehli baat"})
    client.post("/api/turn/text", json={"text": "yaad rakhna aakhri baat"})
    asked = client.post("/api/turn/text", json={"text": "bhool jao last wali baat"}).json()
    assert asked["action"] == "undo_ask" and asked["pending"]
    unclear = client.post("/api/turn/text", json={"text": "pata nahi", "pending": asked["pending"]}).json()
    assert unclear["action"] == "confirm_ask"
    done = client.post("/api/turn/text", json={"text": "haan", "pending": asked["pending"]}).json()
    assert done["action"] == "undone"


def test_quiz_pending_flow(client: TestClient) -> None:
    client.post("/api/turn/text", json={"text": "yaad rakhna maths mein integration ho gaya"})
    asked = client.post("/api/turn/text", json={"text": "quiz karo"}).json()
    assert asked["action"] == "quiz_ask" and asked["pending"]
    answered = client.post(
        "/api/turn/text", json={"text": "integration", "pending": asked["pending"]}
    ).json()
    assert "Sahi jawab" in answered["text"]


def test_audio_turn_end_to_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_stream(pcm, **kwargs):
        assert len(pcm) % 2 == 0
        return TranscriptionResult(text="yaad rakhna audio se aaya", segments=[])

    monkeypatch.setattr(server_mod, "transcribe_pcm", fake_stream)
    res = client.post(
        "/api/turn/audio",
        files={"file": ("turn.wav", _wav16k(), "audio/wav")},
        data={"lang": "hi-IN", "pending": "{}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "saved" and body["transcript"] == "yaad rakhna audio se aaya"


def test_audio_rejects_non_wav(client: TestClient) -> None:
    res = client.post(
        "/api/turn/audio", files={"file": ("x.bin", b"not audio", "application/octet-stream")}, data={}
    )
    assert res.status_code == 400


def test_state_alarms_and_seed(client: TestClient) -> None:
    assert client.post("/api/demo/seed").json() == {"seeded": True}
    state = client.get("/api/state").json()
    assert len(state["notes"]) == 2 and len(state["work"]) == 1 and len(state["watched"]) == 1
    assert client.get("/api/alarms").json() == {"alarms": []}


def test_due_alarm_fires_once(client: TestClient, tmp_path: Path) -> None:
    import os

    from remo.memory import Memory

    mem = Memory(Path(os.environ["REMO_DB"]))
    mem.add_reminder("abhi wala", time.time() - 1)
    mem.close()
    first = client.get("/api/alarms").json()
    assert [a["text"] for a in first["alarms"]] == ["abhi wala"]
    assert client.get("/api/alarms").json() == {"alarms": []}


def test_audio_guard_blocks_traversal(client: TestClient) -> None:
    assert client.get("/api/audio/....wav").status_code == 404
    assert client.get("/api/audio/" + "a" * 40 + ".wav").status_code == 404


def test_speak_stream_proxies_pcm_and_validates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from remo import tts as tts_mod

    assert client.post("/api/speak/stream", json={"text": "  "}).status_code == 400
    assert client.post("/api/speak/stream", json={"text": "x" * 2001}).status_code == 400
    monkeypatch.setattr(tts_mod, "synthesize_stream", lambda *a, **k: iter([b"\x01\x02" * 800]))
    response = client.post("/api/speak/stream", json={"text": "Yaad kar liya."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["X-Audio-Format"] == "pcm16-mono-16000"
    assert len(response.content) % 2 == 0 and len(response.content) > 0


def test_register_login_me_logout_roundtrip(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": "bad", "password": "password-1"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "n@x.co", "password": "short"}).status_code == 400
    created = client.post(
        "/api/auth/register", json={"name": "Asha", "email": "asha@x.co", "password": "password-1"}
    ).json()
    assert created["user"]["email"] == "asha@x.co"
    assert client.get("/api/me").status_code == 401  # register saves, does not sign in
    assert client.post(
        "/api/auth/register", json={"email": "asha@x.co", "password": "password-1"}
    ).status_code == 409
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "asha@x.co", "password": "nope-nope-nope"}).status_code == 401
    assert client.get("/api/me").status_code == 401
    logged = client.post("/api/auth/login", json={"email": "asha@x.co", "password": "password-1"}).json()
    assert logged["user"]["name"] == "Asha"
    assert client.get("/api/me").json()["user"]["email"] == "asha@x.co"
    assert client.post("/api/logout").json() == {"ok": True}
    assert client.get("/api/me").status_code == 401


def test_app_and_api_require_sign_in(client: TestClient) -> None:
    client.cookies.clear()
    app = client.get("/app", follow_redirects=False)
    assert app.status_code == 302 and app.headers["location"] == "/login"
    assert client.get("/api/state").status_code == 401
    assert client.post("/api/turn/text", json={"text": "hi"}).status_code == 401
    assert client.get("/login").status_code == 200
    assert client.get("/").status_code == 200  # landing stays public


def test_login_redirects_when_signed_in(client: TestClient) -> None:
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/app"


def test_google_start_needs_config(client: TestClient) -> None:
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=not_configured"
    assert client.get("/api/auth/providers").json() == {"google": False}


def test_google_callback_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    assert client.get("/api/auth/providers").json() == {"google": True}
    monkeypatch.setattr(server_mod.auth_mod, "google_exchange_code", lambda *a: "tok")
    monkeypatch.setattr(
        server_mod.auth_mod, "google_userinfo",
        lambda *a: {"email": "g@x.co", "email_verified": True, "name": "Gu", "picture": "http://pic"},
    )
    client.cookies.clear()
    started = client.get("/api/auth/google/start", follow_redirects=False)
    assert started.status_code == 302 and "accounts.google.com" in started.headers["location"]
    state = client.cookies.get("remo_oauth_state")
    assert state
    done = client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert done.status_code == 302 and done.headers["location"] == "/app"
    me = client.get("/api/me").json()["user"]
    assert me["email"] == "g@x.co" and me["provider"] == "google" and me["avatar_url"] == "http://pic"


def test_google_callback_rejects_bad_state(client: TestClient) -> None:
    client.cookies.clear()
    done = client.get("/api/auth/google/callback?code=c&state=nope", follow_redirects=False)
    assert done.status_code == 302
    assert done.headers["location"] == "/login?error=expired"
    assert client.get("/api/me").status_code == 401


def test_pdf_import_validates_and_extracts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/api/import/pdf", files={"file": ("x.txt", b"hello")}).status_code == 400
    assert client.post("/api/import/pdf", files={"file": ("x.pdf", b"not a pdf")}).status_code == 400
    big = b"%PDF" + b"0" * (10 * 1024 * 1024)
    assert client.post("/api/import/pdf", files={"file": ("x.pdf", big)}).status_code == 413
    assert client.post("/api/import/pdf", files={"file": ("x.pdf", b"%PDF-1.4 fake")}).status_code == 503
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setattr(
        server_mod.llm_mod, "extract_pdf_notes", lambda *a, **k: ["note one", "note two"]
    )
    done = client.post("/api/import/pdf", files={"file": ("maths.pdf", b"%PDF-1.4 fake")}).json()
    assert done == {"filename": "maths.pdf", "notes": ["note one", "note two"]}


def test_pdf_keep_saves_ticked_notes(client: TestClient) -> None:
    kept = client.post(
        "/api/import/keep", json={"notes": ["  note one  ", "", "note two"], "source": "maths.pdf"}
    ).json()
    assert kept == {"saved": 2}
    notes = client.get("/api/state").json()["notes"]
    assert [n["text"] for n in notes] == ["note two", "note one"]
    assert all(n["source"] == "pdf:maths.pdf" for n in notes)
    assert client.post("/api/import/keep", json={"notes": [], "source": "x"}).status_code == 400


class _FakeLive:
    def __init__(self, *args, on_segment=None, **kwargs) -> None:
        from remo.stt import Segment

        self._on_segment = on_segment
        self._seg = Segment(text="yaad rakhna chai pini hai")
        self.sent: list[bytes] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def send(self, pcm: bytes) -> None:
        self.sent.append(pcm)
        if self._on_segment is not None:
            self._on_segment(self._seg)

    async def finish(self):
        from remo.stt import TranscriptionResult

        return TranscriptionResult(text="yaad rakhna chai pini hai", segments=[self._seg])


def test_audio_stream_turn_end_to_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod, "LiveSession", _FakeLive)
    with client.websocket_connect("/api/turn/audio-stream?lang=hi-IN&pending=%7B%7D") as ws:
        ws.send_bytes(b"\x01" * 3200)
        ws.send_json({"type": "end"})
        frames = []
        for _ in range(5):
            try:
                frames.append(ws.receive_json())
            except Exception:
                break
            if frames[-1].get("type") == "result":
                break
    partials = [f for f in frames if f.get("type") == "partial"]
    results = [f for f in frames if f.get("type") == "result"]
    assert partials and "chai pini hai" in partials[0]["text"]
    assert len(results) == 1
    assert results[0]["action"] == "saved"
    assert results[0]["transcript"] == "yaad rakhna chai pini hai"
    assert results[0]["audio_url"] is None  # text-first; voice via /api/speak
    assert "chai pini hai" in client.get("/api/state").json()["notes"][0]["text"]


def test_audio_stream_rejects_anonymous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMO_DB", str(tmp_path / "remo.db"))
    monkeypatch.setenv("REMO_DATA_DIR", str(tmp_path / "data"))
    anon = TestClient(server_mod.app)
    with anon.websocket_connect("/api/turn/audio-stream") as ws:
        import starlette.websockets as starlette_ws

        try:
            ws.receive_text()
            raise AssertionError("expected close")
        except starlette_ws.WebSocketDisconnect as exc:
            assert exc.code == 4401


def test_audio_stream_rejects_bad_lang(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod, "LiveSession", _FakeLive)
    with client.websocket_connect("/api/turn/audio-stream?lang=xx-YY") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "error"
