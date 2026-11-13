"""Streaming STT: message parsing, headers, session flow with a fake socket."""
import asyncio
import json

import pytest

from remo.config import Settings
from remo.stt import (
    LiveSession,
    parse_server_message,
    stream_headers,
    transcribe_frames,
    valid_boost_words,
)


def test_parse_transcript_message() -> None:
    kind, payload = parse_server_message(
        json.dumps({"type": "transcript", "text": "नमस्ते", "segment_id": "s1", "latency": 320})
    )
    assert kind == "transcript"
    assert payload["segment"].text == "नमस्ते"
    assert payload["segment"].latency_ms == 320


def test_parse_processing_error_and_garbage() -> None:
    assert parse_server_message('{"type": "processing"}')[0] == "processing"
    kind, payload = parse_server_message('{"type": "error", "message": "bad key"}')
    assert kind == "error" and "bad key" in payload["message"]
    assert parse_server_message("not json")[0] == "unknown"
    assert parse_server_message('{"type": "mystery"}')[0] == "unknown"


def test_boost_word_validation() -> None:
    assert valid_boost_words(["viva", "co-op", "GSoC", "214", "viva"]) == ["viva", "GSoC"]
    assert len(valid_boost_words([f"w{i}" for i in range(500)])) <= 100


def test_stream_headers_carry_key_model_and_vad() -> None:
    settings = Settings(gnani_api_key="k", stt_model="prisma-v2.5", language="hi-IN")
    headers = stream_headers(settings, boost_words=["viva"])
    assert headers["x-api-key-id"] == "k"
    assert headers["language_code"] == "hi-IN"
    assert headers["x-sample-rate"] == "16000"
    assert headers["x-min-silence-ms"] == "300"
    assert headers["bias_list"] == "viva"
    assert headers["bias_score"] == "1.0"


class _FakeSocket:
    def __init__(self, incoming: list) -> None:
        self.incoming = list(incoming)
        self.sent: list = []

    async def send(self, data) -> None:  # noqa: ANN001 - test double
        self.sent.append(data)

    async def recv(self):
        if not self.incoming:
            raise asyncio.TimeoutError()
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeConnection:
    def __init__(self, sock: _FakeSocket) -> None:
        self.sock = sock

    async def __aenter__(self):
        return self.sock

    async def __aexit__(self, *args) -> bool:
        return False


def _settings() -> Settings:
    return Settings(gnani_api_key="test-key")


def test_streaming_joins_segments_and_sends_binary() -> None:
    sock = _FakeSocket(
        [
            json.dumps({"type": "processing"}),
            json.dumps({"type": "transcript", "text": "नमस्ते"}),
            json.dumps({"type": "transcript", "text": "कैसे हो"}),
        ]
    )
    result = asyncio.run(
        transcribe_frames(
            [b"\x01" * 1024, b"\x02" * 512],
            settings=_settings(),
            connect_factory=lambda _h: _FakeConnection(sock),
        )
    )
    assert result.text == "नमस्ते कैसे हो"
    assert result.retried is False
    assert len(result.segments) == 2
    assert sock.sent and all(isinstance(f, bytes) and len(f) == 1024 for f in sock.sent)


def test_empty_session_retries_exactly_once() -> None:
    calls = []

    def factory(_headers):
        calls.append(_headers)
        sock = _FakeSocket(
            [] if len(calls) == 1 else [json.dumps({"type": "transcript", "text": "दूसरी बार"})]
        )
        return _FakeConnection(sock)

    result = asyncio.run(
        transcribe_frames([b"\x00" * 1024], settings=_settings(), connect_factory=factory)
    )
    assert result.text == "दूसरी बार"
    assert result.retried is True
    assert len(calls) == 2


def test_server_error_raises() -> None:
    sock = _FakeSocket([json.dumps({"type": "error", "message": "bad key"})])
    with pytest.raises(RuntimeError, match="bad key"):
        asyncio.run(
            transcribe_frames(
                [b"\x00" * 1024], settings=_settings(), connect_factory=lambda _h: _FakeConnection(sock)
            )
        )


def test_missing_key_refuses_to_connect() -> None:
    with pytest.raises(RuntimeError, match="GNANI_API_KEY"):
        asyncio.run(transcribe_frames([b"\x00" * 1024], settings=Settings(gnani_api_key="")))


async def _run_live(sock, chunks):
    partials = []
    async with LiveSession(settings=_settings(), idle_timeout=0.05,
                           connect_factory=lambda _h: _FakeConnection(sock),
                           on_segment=partials.append) as live:
        for chunk in chunks:
            await live.send(chunk)
        result = await live.finish()
    return result, partials, sock


def test_live_session_streams_and_closes_out() -> None:
    sock = _FakeSocket([
        json.dumps({"type": "transcript", "text": "नमस्ते"}),
        json.dumps({"type": "transcript", "text": "कैसे हो"}),
    ])
    result, partials, sock = asyncio.run(_run_live(sock, [b"\x01" * 500, b"\x02" * 2000]))
    assert result.text == "नमस्ते कैसे हो"
    assert result.retried is False
    assert [p.text for p in partials] == ["नमस्ते", "कैसे हो"]
    assert sock.sent and all(isinstance(f, bytes) and len(f) == 1024 for f in sock.sent)
    assert len(sock.sent) > 3  # audio frames plus the silence tail


def test_live_session_replays_buffer_once_when_empty() -> None:
    calls = []

    def factory(_headers):
        calls.append(True)
        sock = _FakeSocket(
            [] if len(calls) == 1 else [json.dumps({"type": "transcript", "text": "दूसरी बार"})]
        )
        factory.socks.append(sock)
        return _FakeConnection(sock)

    factory.socks = []

    async def go():
        async with LiveSession(settings=_settings(), idle_timeout=0.05,
                               connect_factory=factory) as live:
            await live.send(b"\x03" * (21 * 1024))
            return await live.finish()

    result = asyncio.run(go())
    assert result.text == "दूसरी बार"
    assert result.retried is True
    assert len(calls) == 2
    assert sum(len(s.sent) for s in factory.socks) > 21  # replay resent the buffer


def test_live_session_guards_unstarted_use() -> None:
    async def go():
        live = LiveSession(settings=_settings())
        try:
            await live.send(b"\x00" * 100)
            raise AssertionError("send should refuse")
        except RuntimeError:
            pass
        try:
            await live.finish()
            raise AssertionError("finish should refuse")
        except RuntimeError:
            pass

    asyncio.run(go())
