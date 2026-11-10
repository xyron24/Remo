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
    return TestClient(server_mod.app)


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
