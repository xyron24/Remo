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
