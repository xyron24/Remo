"""Gnani Prisma speech-to-text: realtime WebSocket streaming + REST fallback.

Protocol (docs.gnani.ai/api/STT/stt-websocket): headers carry the API key,
language, model, VAD knobs, and optional word-boost / find-and-replace lists.
Audio goes up as 1024-byte binary PCM frames; transcripts come back as
`transcript` JSON messages (each one final). An empty session is retried once.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path

import requests
import websockets

from remo.capture.audio import FRAME_BYTES, iter_frames, silence_tail
from remo.config import Settings, load_settings, require_api_key
from remo.log import get_logger

log = get_logger("stt")


@dataclass
class Segment:
    text: str
    segment_id: str = ""
    latency_ms: int = 0
    language: str = ""


@dataclass
class TranscriptionResult:
    text: str
    segments: list[Segment] = field(default_factory=list)
    retried: bool = False


def parse_server_message(raw: str) -> tuple[str, dict]:
    """Classify one server message: processing | transcript | error | unknown."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "unknown", {}
    kind = msg.get("type", "")
    if kind == "processing":
        return "processing", {}
    if kind == "transcript":
        segment = Segment(
            text=str(msg.get("text", "")),
            segment_id=str(msg.get("segment_id", "")),
            latency_ms=int(msg.get("latency", 0) or 0),
            language=str(msg.get("detected_language_code", "")),
        )
        return "transcript", {"segment": segment}
    if kind == "error":
        return "error", {"message": str(msg.get("message", msg))}
    return "unknown", {"raw": msg}


def valid_boost_words(words: Iterable[str], limit: int = 100) -> list[str]:
    """Keep letters-only single words; one bad word must not nuke the list."""
    clean: list[str] = []
    for word in words:
        word = word.strip()
        if word and word.isalpha() and word not in clean:
            clean.append(word)
        if len(clean) >= limit:
            break
    return clean


def stream_headers(
    settings: Settings,
    *,
    sample_rate: int = 16000,
    silence_ms: int = 300,
    boost_words: Iterable[str] = (),
    bias_score: str = "1.0",
    substitutions_json: str = "",
) -> dict[str, str]:
    """Build the WebSocket upgrade headers for a streaming session."""
    headers = {
        "x-api-key-id": settings.gnani_api_key,
        "language_code": settings.language,
        "model": settings.stt_model,
        "x-sample-rate": str(sample_rate),
        "x-min-silence-ms": str(silence_ms),
    }
    boosted = valid_boost_words(boost_words)
    if boosted:
        headers["bias_list"] = ",".join(boosted)
        headers["bias_score"] = bias_score
    if substitutions_json:
        headers["enable_substitution"] = "true"
        headers["substitution_map"] = substitutions_json
    return headers


async def _run_session(
    frames: Iterable[bytes],
    headers: dict[str, str],
    url: str,
    connect: AbstractAsyncContextManager,
    idle_timeout: float,
    tail_ms: int,
    sample_rate: int,
) -> list[Segment]:
    segments: list[Segment] = []
    async with connect as ws:
        for piece in frames:
            for frame in iter_frames(piece):
                await ws.send(frame)
        tail = silence_tail(tail_ms, sample_rate)
        for frame in iter_frames(tail):
            await ws.send(frame)
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                break
            kind, payload = parse_server_message(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
            if kind == "transcript":
                segment = payload["segment"]
                if segment.text.strip():
                    segments.append(segment)
            elif kind == "error":
                raise RuntimeError(f"Prisma streaming error: {payload['message']}")
    return segments


async def transcribe_frames(
    frames: Iterable[bytes],
    *,
    settings: Settings | None = None,
    sample_rate: int = 16000,
    silence_ms: int = 300,
    tail_ms: int = 600,
    idle_timeout: float = 3.0,
    total_timeout: float = 60.0,
    boost_words: Iterable[str] = (),
    connect_factory: Callable[[dict[str, str]], AbstractAsyncContextManager] | None = None,
) -> TranscriptionResult:
    """Stream PCM frames to Prisma; retry once when nothing comes back."""
    settings = settings or load_settings()
    require_api_key(settings)
    headers = stream_headers(settings, sample_rate=sample_rate, silence_ms=silence_ms, boost_words=boost_words)
    frames = list(frames)

    def default_factory() -> AbstractAsyncContextManager:
        return websockets.connect(settings.stt_stream_url, additional_headers=headers)

    factory = connect_factory or (lambda _h: default_factory())

    async def attempt() -> list[Segment]:
        return await asyncio.wait_for(
            _run_session(frames, headers, settings.stt_stream_url, factory(headers),
                         idle_timeout, tail_ms, sample_rate),
            timeout=total_timeout,
        )

    segments = await attempt()
    retried = False
    if not segments:
        log.info("Empty streaming result, retrying once.")
        segments = await attempt()
        retried = True
    text = " ".join(s.text.strip() for s in segments if s.text.strip())
    return TranscriptionResult(text=text, segments=segments, retried=retried)


def transcribe_pcm(pcm: bytes, **kwargs) -> TranscriptionResult:
    """Sync wrapper: stream raw 16-bit mono PCM bytes through Prisma."""
    return asyncio.run(transcribe_frames(iter_frames(pcm, FRAME_BYTES), **kwargs))


class LiveSession:
    """Incremental streaming: frames go up as they arrive; finish() closes out.

    Usage:
        async with LiveSession(settings=settings) as live:
            await live.send(pcm_chunk)  # 16-bit mono PCM, any size
            ...
            result = await live.finish()  # tail + drain + TranscriptionResult

    An empty first attempt replays the buffered audio once on a fresh
    connection, mirroring transcribe_frames.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        sample_rate: int = 16000,
        silence_ms: int = 300,
        tail_ms: int = 600,
        idle_timeout: float = 3.0,
        boost_words: Iterable[str] = (),
        connect_factory: Callable[[dict[str, str]], AbstractAsyncContextManager] | None = None,
        on_segment: Callable[[Segment], None] | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        require_api_key(self._settings)
        self._sample_rate = sample_rate
        self._tail_ms = tail_ms
        self._idle_timeout = idle_timeout
        self._factory = connect_factory
        self._on_segment = on_segment
        self._headers = stream_headers(
            self._settings, sample_rate=sample_rate, silence_ms=silence_ms, boost_words=boost_words
        )
        self._incoming: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._done = asyncio.Event()
        self._segments: list[Segment] = []
        self._buffer = bytearray()
        self._ws_cm: AbstractAsyncContextManager | None = None
        self._ws = None
        self._sender: asyncio.Task | None = None
        self._receiver: asyncio.Task | None = None
        self._retried = False

    def _connect(self) -> AbstractAsyncContextManager:
        if self._factory is not None:
            return self._factory(self._headers)
        return websockets.connect(self._settings.stt_stream_url, additional_headers=self._headers)

    async def __aenter__(self) -> LiveSession:
        self._ws_cm = self._connect()
        self._ws = await self._ws_cm.__aenter__()
        self._sender = asyncio.create_task(self._pump())
        self._receiver = asyncio.create_task(self._drain())
        return self

    async def __aexit__(self, *args) -> bool:
        for task in (self._sender, self._receiver):
            if task is not None:
                task.cancel()
        if self._ws_cm is not None:
            try:
                await self._ws_cm.__aexit__(*args)
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - closing must not raise
                pass
        return False

    async def _pump(self) -> None:
        assert self._ws is not None
        while True:
            chunk = await self._incoming.get()
            if chunk is None:
                for frame in iter_frames(silence_tail(self._tail_ms, self._sample_rate)):
                    await self._ws.send(frame)
                return
            for frame in iter_frames(chunk):
                await self._ws.send(frame)

    def _ingest(self, raw: str | bytes) -> None:
        kind, payload = parse_server_message(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        if kind == "transcript":
            segment = payload["segment"]
            if segment.text.strip():
                self._segments.append(segment)
                if self._on_segment is not None:
                    self._on_segment(segment)
        elif kind == "error":
            raise RuntimeError(f"Prisma streaming error: {payload['message']}")

    async def _drain(self) -> None:
        assert self._ws is not None
        while not self._done.is_set():
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
            except asyncio.TimeoutError:
                await asyncio.sleep(0.01)
                continue
            self._ingest(raw)

    async def _drain_final(self, grace: float = 0.5) -> None:
        """After the tail: first transcript (or cap), then a short grace hush."""
        assert self._ws is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._idle_timeout
        heard = False
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=min(remaining, grace if heard else remaining))
            except asyncio.TimeoutError:
                if heard:
                    return
                continue
            self._ingest(raw)
            heard = True

    async def send(self, pcm: bytes) -> None:
        """Queue raw PCM for upload; safe to call with any chunk size."""
        if self._sender is None:
            raise RuntimeError("LiveSession.send before start")
        if pcm:
            self._buffer += pcm
            await self._incoming.put(bytes(pcm))

    async def finish(self) -> TranscriptionResult:
        """End the stream: tail, drain, close; retry once when empty."""
        if self._sender is None or self._receiver is None:
            raise RuntimeError("LiveSession.finish before start")
        await self._incoming.put(None)
        await self._sender
        self._done.set()
        if self._receiver is not None:
            self._receiver.cancel()
            try:
                await self._receiver
            except asyncio.CancelledError:
                pass
        await self._drain_final()
        if not self._segments and not self._retried and len(self._buffer) >= 20 * FRAME_BYTES:
            log.info("Empty live result, replaying buffered audio once.")
            self._retried = True
            return await self._replay()
        return self._result()

    def _result(self) -> TranscriptionResult:
        text = " ".join(s.text.strip() for s in self._segments if s.text.strip())
        return TranscriptionResult(text=text, segments=list(self._segments), retried=self._retried)

    async def _replay(self) -> TranscriptionResult:
        buffered = bytes(self._buffer)
        replay = LiveSession(
            settings=self._settings,
            sample_rate=self._sample_rate,
            tail_ms=self._tail_ms,
            idle_timeout=self._idle_timeout,
            connect_factory=self._factory,
        )
        replay._retried = True  # this IS the retry; never recurse
        async with replay:
            await replay.send(buffered)
            result = await replay.finish()
        result.retried = True
        return result


def transcribe_file_rest(path: Path, language: str | None = None, timeout: int = 60) -> str:
    """One-shot REST transcription for short pre-recorded clips (<=30 s)."""
    settings = load_settings()
    api_key = require_api_key(settings)
    with path.open("rb") as f:
        resp = requests.post(
            settings.stt_url,
            headers={"X-API-Key-ID": api_key},
            files={"audio_file": (path.name, f, "audio/wav")},
            data={"model": settings.stt_model, "language_code": language or settings.language},
            timeout=timeout,
        )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success", True):
        raise RuntimeError(f"Prisma error: {body}")
    return str(body.get("transcript", ""))
