"""Gnani Timbre voice-out: every reply spoken, one request at a time.

Timbre allows a single active request, so all synthesis goes through one lock.
Audio is cached on disk by content hash , repeated phrases cost nothing.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import requests

from remo import lang as lang_mod
from remo.config import Settings, load_settings, require_api_key
from remo.log import get_logger
from remo.paths import data_dir

log = get_logger("tts")

_LOCK = threading.Lock()


def _cache_key(text: str, settings: Settings, speed: float) -> str:
    raw = "|".join([settings.tts_model, settings.tts_voice, settings.language, str(speed), text])
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
                        "sample_rate": 48000,
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
