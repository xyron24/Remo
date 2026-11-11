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


def test_compose_returns_grounded_text_and_sends_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float = 0):
        seen["url"] = url
        seen["body"] = json
        return _ok_response("Kal kirana se atta lena hai.")

    monkeypatch.setattr("remo.llm.requests.post", fake_post)
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
    monkeypatch.setattr("remo.llm.requests.post", lambda *a, **k: FakeResponse(payload))
    assert L.compose("q?", ["note"], api_key="g-test") is None


def test_compose_failures_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr("remo.llm.requests.post", boom)
    assert L.compose("q?", ["note"], api_key="g-test") is None
    monkeypatch.setattr("remo.llm.requests.post", lambda *a, **k: _ok_response("   "))
    assert L.compose("q?", ["note"], api_key="g-test") is None
    assert L.compose("q?", ["note"], api_key="") is None
    assert L.compose("q?", [], api_key="g-test") is None


def test_compose_truncates_long_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remo.llm.requests.post", lambda *a, **k: _ok_response("x" * 2000))
    out = L.compose("q?", ["note"], api_key="g-test")
    assert out is not None and len(out) <= L.MAX_CHARS


def test_try_compose_dead_end_without_key(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    note = mem.add_note("kal kirana se atta lena hai")
    assert L.try_compose("kal kya lena hai?", [note], mem, Settings()) is None
    mem.close()
