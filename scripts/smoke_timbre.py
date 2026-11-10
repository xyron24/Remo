"""Smoke test: Gnani Timbre text-to-speech (REST).

Synthesizes Hindi speech to out/hello.wav (which smoke_prisma.py then
transcribes back — a full round-trip through both Gnani speech models).

Usage:
    python scripts/smoke_timbre.py [--text "..."] [--out out/hello.wav]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from remo.config import load_settings, require_api_key
from remo.log import get_logger

log = get_logger("smoke_timbre")

DEFAULT_TEXT = "नमस्ते, मैं रेमो हूँ।"


def synthesize(text: str, out_path: Path, timeout: int = 60) -> int:
    settings = load_settings()
    api_key = require_api_key(settings)
    resp = requests.post(
        settings.tts_url,
        headers={"X-API-Key-ID": api_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "voice": settings.tts_voice,
            "model": settings.tts_model,
            "language": settings.language,
            "speed": 1.0,
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return len(resp.content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize speech via Gnani Timbre.")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out", default="out/hello.wav")
    args = parser.parse_args()

    try:
        size = synthesize(args.text, Path(args.out))
    except Exception as exc:  # noqa: BLE001 - smoke script reports and exits nonzero
        log.error("Timbre smoke test FAILED: %s", exc)
        return 1
    log.info("Timbre smoke test PASSED. Wrote %s (%d bytes).", args.out, size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
