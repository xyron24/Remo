"""TTS client: request shape, disk cache, graceful behavior."""
from pathlib import Path

import pytest

from remo import tts
from remo.config import Settings


class _FakeResponse:
    def __init__(self, payload: bytes = b"RIFF" + b"\x00" * 100) -> None:
        self.content = payload

    def raise_for_status(self) -> None:
        pass


def _settings() -> Settings:
    return Settings(gnani_api_key="test-key")


def test_synthesize_posts_timbre_shape_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REMO_DATA_DIR", str(tmp_path))
    calls: list = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse()

    monkeypatch.setattr(tts.requests, "post", fake_post)
    out = tmp_path / "hello.wav"
    first = tts.synthesize("नमस्ते", settings=_settings(), out=out)
    assert first == out and out.stat().st_size > 100
    assert calls[0]["url"].endswith("/api/v1/tts/inference")
    assert calls[0]["headers"]["X-API-Key-ID"] == "test-key"
    assert calls[0]["json"]["model"] == "timbre-v2.5"

    second = tts.synthesize("नमस्ते", settings=_settings())
    assert second.exists() and len(calls) == 1, "repeat phrase must hit the cache"


def test_missing_key_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMO_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="GNANI_API_KEY"):
        tts.synthesize("hi", settings=Settings(gnani_api_key=""))
