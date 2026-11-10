"""Live smoke tests: Timbre speaks, Prisma listens (round-trip).

Skipped automatically when GNANI_API_KEY is not set, so plain `pytest`
stays green offline. Run live with:

    pytest -m live
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from remo.config import load_settings

pytestmark = pytest.mark.live

needs_key = pytest.mark.skipif(
    not os.environ.get("GNANI_API_KEY") and not Path(".env").exists(),
    reason="GNANI_API_KEY not set (copy .env.example to .env)",
)


@needs_key
def test_timbre_then_prisma_roundtrip(tmp_path: Path) -> None:
    from scripts.smoke_timbre import synthesize

    from remo.stt import transcribe_file_rest

    settings = load_settings()
    assert settings.gnani_api_key, "GNANI_API_KEY must be set for live tests"

    wav = tmp_path / "hello.wav"
    size = synthesize("नमस्ते, मैं रेमो हूँ।", wav)
    assert size > 1000, "TTS returned suspiciously little audio"

    transcript = transcribe_file_rest(wav, settings.language)
    assert transcript.strip(), "STT returned an empty transcript"


@needs_key
def test_streaming_transcription_live(tmp_path: Path) -> None:
    """File audio over the realtime WebSocket: TTS 48 kHz -> 16 kHz -> stream."""
    import wave

    from scripts.smoke_timbre import synthesize

    from remo.capture.audio import downsample_mono16
    from remo.stt import transcribe_pcm

    settings = load_settings()
    assert settings.gnani_api_key, "GNANI_API_KEY must be set for live tests"

    wav = tmp_path / "stream.wav"
    synthesize("याद रखना, गणित में काम बाकी है।", wav)
    with wave.open(str(wav), "rb") as handle:
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())
    pcm16 = downsample_mono16(pcm, rate, 16000)
    result = transcribe_pcm(pcm16, settings=settings, sample_rate=16000)
    assert result.text.strip(), "streaming STT returned an empty transcript"
