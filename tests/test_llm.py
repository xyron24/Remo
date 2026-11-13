"""LLM composer: grounded Gemini answers with extractive fallback."""
from pathlib import Path

import pytest

from remo import llm as L
from remo.config import Settings
from remo.memory import Memory


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


def _ok_response(text: str) -> FakeResponse:
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})


class _FakeSession:
    def __init__(self, post) -> None:
        self._post = post

    def post(self, *args, **kwargs):
        return self._post(*args, **kwargs)


def _stub_transport(monkeypatch: pytest.MonkeyPatch, post) -> None:
    monkeypatch.setattr("remo.llm._http", lambda: _FakeSession(post))


@pytest.fixture(autouse=True)
def _fresh_cooldowns(tmp_path):
    L._COOLDOWNS.clear()
    L._LAST_OK.clear()
    L.configure_health(str(tmp_path / "health.json"))
    yield
    L._COOLDOWNS.clear()
    L._LAST_OK.clear()
    L.configure_health(None)


def test_compose_returns_grounded_text_and_sends_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["url"] = url
        seen["body"] = json
        return _ok_response("Kal kirana se atta lena hai.")

    _stub_transport(monkeypatch, fake_post)
    out = L.compose(
        "kal kya lena hai?",
        ["kal kirana se atta aur dal lena hai"],
        api_key="g-test",
    )
    assert out == "Kal kirana se atta lena hai."
    assert "gemini-2.5-flash" in seen["url"]
    blob = str(seen["body"])
    assert "kal kirana se atta" in blob and "kal kya lena hai" in blob
    assert "ONLY" in blob


@pytest.mark.parametrize("payload", [{}, {"candidates": []}, {"candidates": [{"content": {}}]}])
def test_compose_malformed_payload_returns_none(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    _stub_transport(monkeypatch, lambda *a, **k: FakeResponse(payload))
    assert L.compose("q?", ["note"], api_key="g-test") is None


def test_compose_failures_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise TimeoutError("slow")

    _stub_transport(monkeypatch, boom)
    assert L.compose("q?", ["note"], api_key="g-test") is None
    _stub_transport(monkeypatch, lambda *a, **k: _ok_response("   "))
    assert L.compose("q?", ["note"], api_key="g-test") is None
    assert L.compose("q?", ["note"], api_key="") is None
    assert L.compose("q?", [], api_key="g-test") is None


def test_compose_truncates_long_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_transport(monkeypatch, lambda *a, **k: _ok_response("x" * 2000))
    out = L.compose("q?", ["note"], api_key="g-test")
    assert out is not None and len(out) <= L.MAX_CHARS


def test_quota_moves_to_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    calls: list[str] = []

    def flaky(url: str, json: dict | None = None, timeout: float = 0):
        calls.append(url)
        if "2.5-flash" in url:
            response = requests.Response()
            response.status_code = 429
            raise requests.HTTPError("quota", response=response)
        return _ok_response("second model answers.")

    _stub_transport(monkeypatch, flaky)
    out = L.compose("q?", ["note"], api_key="g-test")
    assert out == "second model answers."
    assert len(calls) == 2 and "3-flash" in calls[1]


def test_auth_error_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    calls: list[str] = []

    def denied(url: str, json: dict | None = None, timeout: float = 0):
        calls.append(url)
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError("denied", response=response)

    _stub_transport(monkeypatch, denied)
    assert L.compose("q?", ["note"], api_key="bad") is None
    assert len(calls) == 1


def test_dead_key_moves_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    calls: list[str] = []

    def flaky(url: str, json: dict | None = None, timeout: float = 0):
        calls.append(url)
        if "key=AAA" in url:
            response = requests.Response()
            response.status_code = 429
            raise requests.HTTPError("quota", response=response)
        return _ok_response("second key answers.")

    _stub_transport(monkeypatch, flaky)
    out = L.compose("q?", ["note"], models=["m1"], api_keys=["AAA", "BBB"])
    assert out == "second key answers."
    assert any("key=BBB" in url for url in calls)


def test_quota_dead_combo_is_skipped_next_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    calls: list[str] = []

    def flaky(url: str, json: dict | None = None, timeout: float = 0):
        calls.append(url)
        if "m1" in url:
            response = requests.Response()
            response.status_code = 429
            raise requests.HTTPError("quota, retry in 5s", response=response)
        return _ok_response("ok")

    _stub_transport(monkeypatch, flaky)
    assert L.compose("q?", ["note"], models=["m1", "m2"], api_keys=["K"]) == "ok"
    assert L.compose("q?", ["note"], models=["m1", "m2"], api_keys=["K"]) == "ok"
    assert len([u for u in calls if "m1" in u]) == 1
    assert len([u for u in calls if "m2" in u]) == 2


def test_bare_429_cools_down_longer_than_transients() -> None:
    import requests

    def err(status: int, message: str) -> requests.HTTPError:
        response = requests.Response()
        response.status_code = status
        return requests.HTTPError(message, response=response)

    assert L._cooldown_seconds(err(429, "quota exceeded"), 429) == 600.0
    assert L._cooldown_seconds(err(503, "overloaded"), 503) == 60.0
    assert L._cooldown_seconds(err(429, "quota, retry in 5s"), 429) == 6.0


def test_slow_first_race_is_won_by_second(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    calls: list[str] = []

    def flaky(url: str, json: dict | None = None, timeout: float = 0):
        calls.append(url)
        if "m1" in url:
            _time.sleep(0.5)
            return _ok_response("too slow")
        return _ok_response("hedge wins")

    monkeypatch.setattr(L, "HEDGE_AFTER_SECONDS", 0.05)
    _stub_transport(monkeypatch, flaky)
    start = _time.time()
    assert L.compose("q?", ["note"], models=["m1", "m2"], api_keys=["K"]) == "hedge wins"
    assert _time.time() - start < 0.45
    assert len(calls) == 2


def test_all_cooling_fails_fast_without_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    def always_quota(url: str, json: dict | None = None, timeout: float = 0):
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError("quota", response=response)

    _stub_transport(monkeypatch, always_quota)
    assert L.compose("q?", ["note"], models=["m1"], api_keys=["K"]) is None
    calls: list[str] = []
    _stub_transport(monkeypatch, lambda *a, **k: calls.append(1) or _ok_response("x"))
    assert L.compose("q?", ["note"], models=["m1"], api_keys=["K"]) is None
    assert calls == []


def test_cooldown_survives_restart(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import requests

    def always_quota(url: str, json: dict | None = None, timeout: float = 0):
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError("quota", response=response)

    _stub_transport(monkeypatch, always_quota)
    assert L.compose("q?", ["note"], models=["m1"], api_keys=["K"]) is None
    assert (tmp_path / "health.json").exists()
    L._COOLDOWNS.clear()
    L.configure_health(str(tmp_path / "health.json"))  # fresh process, same file
    calls: list[str] = []
    _stub_transport(monkeypatch, lambda *a, **k: calls.append(1) or _ok_response("x"))
    assert L.compose("q?", ["note"], models=["m1"], api_keys=["K"]) is None
    assert calls == []


def test_last_working_combo_goes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_transport(monkeypatch, lambda url, **k: calls.append(url) or _ok_response("ok"))
    assert L.compose("q?", ["note"], models=["m1", "m2"], api_keys=["K"]) == "ok"
    L._LAST_OK[L._cool_key("K", "m2")] = 9999999999.0
    L.compose("q?", ["note"], models=["m1", "m2"], api_keys=["K"])
    assert "m2" in calls[-1] and "m1" not in calls[-1]


def test_extract_pdf_notes_parses_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["body"] = json
        return _ok_response("1. Integration is area under a curve\n- Differential is slope\n\nPhotosynthesis needs sun.")

    _stub_transport(monkeypatch, fake_post)
    notes = L.extract_pdf_notes(b"%PDF-fake", filename="maths.pdf", api_key="g-test")
    assert notes == ["Integration is area under a curve", "Differential is slope", "Photosynthesis needs sun."]
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "application/pdf"


def test_extract_pdf_notes_caps_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_transport(monkeypatch, lambda *a, **k: _ok_response("\n".join(f"n{i}" for i in range(30))))
    notes = L.extract_pdf_notes(b"%PDF-fake", api_key="g-test")
    assert notes is not None and len(notes) == 12
    assert L.extract_pdf_notes(b"", api_key="g-test") is None
    assert L.extract_pdf_notes(b"%PDF-fake", api_key="") is None

    def boom(*args, **kwargs):
        raise TimeoutError("slow")

    _stub_transport(monkeypatch, boom)
    assert L.extract_pdf_notes(b"%PDF-fake", api_key="g-test") is None


def test_compose_briefing_lists_work_then_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["body"] = json
        return _ok_response("Docs baaki hai, aur ek naya comment aaya.")

    _stub_transport(monkeypatch, fake_post)
    out = L.compose_briefing(["docs baaki hai"], ["Naya comment aaya."], api_key="g-test")
    assert out == "Docs baaki hai, aur ek naya comment aaya."
    blob = str(seen["body"])
    assert "docs baaki hai" in blob and "Naya comment" in blob
    assert L.compose_briefing([], [], api_key="g-test") is None


def test_compose_left_off_full_combines_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["body"] = json
        return _ok_response("Ye bacha hai: differential. Aur 1 task aur 1 reminder bhi hai.")

    _stub_transport(monkeypatch, fake_post)
    out = L.compose_left_off_full(["differential baaki hai"], ["docs likhna hai"], ["chai (5 baje)"],
                                  api_key="g-test")
    assert out is not None and "differential" in out
    blob = str(seen["body"])
    assert "docs likhna hai" in blob and "chai (5 baje)" in blob
    assert L.compose_left_off_full([], [], [], api_key="g-test") is None
    assert L.compose_left_off_full(["x"], [], [], api_key="") is None


def test_try_left_off_wires_keys_and_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_transport(monkeypatch, lambda *a, **k: _ok_response("Sab baaki hai."))
    mem = Memory(tmp_path / "remo.db")
    note = mem.add_note("differential baaki hai")
    out = L.try_left_off([note], ["docs"], ["chai (5 baje)"],
                         Settings(gemini_api_keys=("k1", "k2")))
    assert out == "Sab baaki hai."
    assert L.try_left_off([note], [], [], Settings()) is None
    mem.close()


def test_try_compose_dead_end_without_key(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    note = mem.add_note("kal kirana se atta lena hai")
    assert L.try_compose("kal kya lena hai?", [note], mem, Settings()) is None
    mem.close()


def test_parse_intent_reads_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_transport(
        monkeypatch,
        lambda *a, **k: _ok_response('{"intent": "save", "save_text": "ye sab karna"}'),
    )
    parsed = L.parse_intent("remember, ye sab karna", api_key="g-test")
    assert parsed == {"intent": "save", "save_text": "ye sab karna"}


def test_parse_intent_carries_context_and_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["body"] = json
        return _ok_response('{"intent": "recall", "query": "q", "reply": "Atta lena hai."}')

    _stub_transport(monkeypatch, fake_post)
    parsed = L.parse_intent("q?", context="Notes:\n- atta lena hai", api_key="g-test")
    assert parsed is not None and parsed["reply"] == "Atta lena hai."
    assert "atta lena hai" in str(seen["body"])


def test_parse_intent_tolerates_fences_and_rejects_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_transport(
        monkeypatch,
        lambda *a, **k: _ok_response('```json\n{"intent": "other", "reply": "Namaste!"}\n```'),
    )
    assert L.parse_intent("namaste", api_key="g-test") == {"intent": "other", "reply": "Namaste!"}
    _stub_transport(monkeypatch, lambda *a, **k: _ok_response("not json"))
    assert L.parse_intent("namaste", api_key="g-test") is None
    _stub_transport(
        monkeypatch, lambda *a, **k: _ok_response('{"intent": "teleport"}')
    )
    assert L.parse_intent("namaste", api_key="g-test") is None
    assert L.parse_intent("namaste", api_key="") is None
    mem = Memory(":memory:")
    assert L.try_intent("namaste", mem, Settings()) is None
    mem.close()
