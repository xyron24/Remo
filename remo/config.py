"""Runtime configuration for Remo.

Reads from the environment, with optional `.env` file support parsed using only
the standard library (so setup needs no extra dependencies).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; blanks and # comments ignored."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    gnani_api_key: str = ""
    github_token: str = ""
    stt_url: str = "https://api.vachana.ai/stt/v3"
    stt_stream_url: str = "wss://api.vachana.ai/stt/v3/stream"
    stt_model: str = "prisma-v2.5"
    tts_url: str = "https://api.vachana.ai/api/v1/tts/inference"
    tts_model: str = "timbre-v2.5"
    tts_voice: str = "Nalini"
    language: str = "hi-IN"


def load_settings(env_path: Path | None = None) -> Settings:
    """Load settings from environment (+ `.env` file if present)."""
    _load_dotenv(env_path or Path(".env"))
    get = os.environ.get
    defaults = Settings()
    return Settings(
        gnani_api_key=get("GNANI_API_KEY", ""),
        github_token=get("GITHUB_TOKEN", ""),
        stt_url=get("GNANI_STT_URL", defaults.stt_url),
        stt_stream_url=get("GNANI_STT_STREAM_URL", defaults.stt_stream_url),
        stt_model=get("GNANI_STT_MODEL", defaults.stt_model),
        tts_url=get("GNANI_TTS_URL", defaults.tts_url),
        tts_model=get("GNANI_TTS_MODEL", defaults.tts_model),
        tts_voice=get("GNANI_TTS_VOICE", defaults.tts_voice),
        language=get("REMO_LANG", defaults.language),
    )


def require_api_key(settings: Settings) -> str:
    """Return the Gnani API key or raise with setup instructions."""
    if not settings.gnani_api_key:
        raise RuntimeError(
            "GNANI_API_KEY is missing. Copy .env.example to .env and paste your key "
            "from https://app.gnani.ai/voice (register at "
            "https://www.gnani.ai/great-indian-ai-internship-registration-form first)."
        )
    return settings.gnani_api_key
