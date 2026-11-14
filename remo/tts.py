"""Gnani Timbre voice-out: every reply spoken, one request at a time.

Timbre allows a single active request, so all synthesis goes through one lock.
Audio is cached on disk by content hash , repeated phrases cost nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from collections.abc import Iterator
from pathlib import Path

import requests

from remo import lang as lang_mod
from remo.config import Settings, load_settings, require_api_key
from remo.log import get_logger
from remo.paths import data_dir

log = get_logger("tts")

_LOCK = threading.Lock()

# 16 kHz keeps voice quality while synthesizing ~25% faster than 48 kHz
# and producing 3x smaller files.
SAMPLE_RATE = 16000


def _cache_key(text: str, settings: Settings, speed: float) -> str:
    raw = "|".join([settings.tts_model, settings.tts_voice, settings.language,
                    str(speed), str(SAMPLE_RATE), text])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def synthesize(
    text: str,
    *,
    settings: Settings | None = None,
    out: Path | str | None = None,
    use_cache: bool = True,
    speed: float = 1.0,
    timeout: int = 60,
) -> Path:
    """Speak `text` via Timbre; returns the WAV path (cached copy by default)."""
    settings = settings or load_settings()
    api_key = require_api_key(settings)
    voice = lang_mod.resolve_voice(settings.tts_voice, settings.language)
    voice_settings = Settings(
        gnani_api_key=settings.gnani_api_key,
        github_token=settings.github_token,
        stt_url=settings.stt_url,
        stt_stream_url=settings.stt_stream_url,
        stt_model=settings.stt_model,
        tts_url=settings.tts_url,
        tts_model=settings.tts_model,
        tts_voice=voice,
        language=settings.language,
    )
    cached = data_dir() / "tts_cache" / f"{_cache_key(text, voice_settings, speed)}.wav"
    if use_cache and cached.exists():
        payload = cached.read_bytes()
    else:
        with _LOCK:
            resp = requests.post(
                settings.tts_url,
                headers={"X-API-Key-ID": api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "voice": voice,
                    "model": settings.tts_model,
                    "language": settings.language,
                    "speed": speed,
                    "audio_config": {
                        "sample_rate": SAMPLE_RATE,
                        "num_channels": 1,
                        "sample_width": 2,
                        "encoding": "linear_pcm",
                        "container": "wav",
                    },
                },
                timeout=timeout,
            )
        resp.raise_for_status()
        payload = resp.content
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(payload)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        return out_path
    return cached


def pregenerate(phrases: list[str], **kwargs) -> list[Path]:
    """Warm the cache for fixed phrases (acks, prompts) ahead of time."""
    return [synthesize(phrase, **kwargs) for phrase in phrases]


def _wav_header(data_len: int, sample_rate: int = SAMPLE_RATE) -> bytes:
    header = bytearray(44)
    header[0:4] = b"RIFF"
    struct.pack_into("<I", header, 4, 36 + data_len)
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    struct.pack_into("<IHHIIHH", header, 16, 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header[36:40] = b"data"
    struct.pack_into("<I", header, 40, data_len)
    return bytes(header)


def _iter_sse_audio(resp) -> Iterator[bytes]:
    """Yield raw PCM chunks from a Timbre SSE response (base64 `audio` fields)."""
    for line in resp.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        if not text.startswith("data:"):
            continue
        try:
            payload = json.loads(text[5:].strip())
        except ValueError:
            continue
        audio = payload.get("audio")
        if audio:
            yield base64.b64decode(audio)
        if payload.get("is_final"):
            return


def _sse_url() -> str:
    return "https://api.vachana.ai/api/v1/tts/sse"


def synthesize_stream(
    text: str,
    *,
    settings: Settings | None = None,
    speed: float = 1.0,
    timeout: int = 60,
) -> Iterator[bytes]:
    """Yield raw 16-bit mono PCM chunks as Timbre generates them.

    Cache hits replay the stored file progressively; misses proxy the SSE
    stream and write the assembled WAV to cache on clean completion.
    Shares cache files with synthesize().
    """
    settings = settings or load_settings()
    api_key = require_api_key(settings)
    voice = lang_mod.resolve_voice(settings.tts_voice, settings.language)
    voice_settings = Settings(
        gnani_api_key=settings.gnani_api_key,
        tts_model=settings.tts_model,
        tts_voice=voice,
        language=settings.language,
    )
    cached = data_dir() / "tts_cache" / f"{_cache_key(text, voice_settings, speed)}.wav"
    if cached.exists():
        raw = cached.read_bytes()[44:]  # strip the WAV header, keep the PCM
        for offset in range(0, len(raw), 3200):
            yield raw[offset : offset + 3200]
        return
    assembled = bytearray()
    with _LOCK:
        resp = requests.post(
            _sse_url(),
            headers={"X-API-Key-ID": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "voice": voice,
                "model": settings.tts_model,
                "language": settings.language,
                "speed": speed,
                "audio_config": {
                    "sample_rate": SAMPLE_RATE,
                    "num_channels": 1,
                    "sample_width": 2,
                    "encoding": "linear_pcm",
                    "container": "raw",
                },
            },
            timeout=timeout,
            stream=True,
        )
        resp.raise_for_status()
        for chunk in _iter_sse_audio(resp):
            assembled += chunk
            yield bytes(chunk)
    if assembled:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(_wav_header(len(assembled)) + bytes(assembled))
