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


class _FakeSSE:
    def __init__(self, chunks: list[bytes]) -> None:
        import base64
        import json

        lines = ['event: start', 'data: {"status": "streaming_started"}', ""]
        for i, chunk in enumerate(chunks):
            lines += ["event: chunk",
                      "data: " + json.dumps({"chunk_index": i, "audio": base64.b64encode(chunk).decode()})]
        lines += ["event: complete", 'data: {"is_final": true}']
        self._lines = [line.encode() for line in lines]

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self):
        return iter(self._lines)


def test_synthesize_stream_reassembles_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REMO_DATA_DIR", str(tmp_path))
    calls: list = []

    def fake_post(url, headers=None, json=None, timeout=None, stream=None):
        calls.append({"url": url, "json": json, "stream": stream})
        return _FakeSSE([b"\x01\x02" * 100, b"\x03\x04" * 100])

    monkeypatch.setattr(tts.requests, "post", fake_post)
    chunks = list(tts.synthesize_stream("hello there", settings=_settings()))
    assert b"".join(chunks) == b"\x01\x02" * 100 + b"\x03\x04" * 100
    assert calls[0]["url"].endswith("/api/v1/tts/sse")
    assert calls[0]["json"]["audio_config"]["container"] == "raw"
    assert calls[0]["json"]["audio_config"]["sample_rate"] == 16000

    replayed = list(tts.synthesize_stream("hello there", settings=_settings()))
    assert replayed and b"".join(replayed) == b"".join(chunks)
    assert len(calls) == 1, "second play must come from cache"

    import wave as _wave

    cached = next((tmp_path / "tts_cache").glob("*.wav"))
    with _wave.open(str(cached), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.getnframes() * 2 == len(b"".join(chunks))
