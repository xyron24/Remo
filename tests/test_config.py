"""Offline config tests: defaults, .env parsing, key requirement."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from remo.config import Settings, load_settings, require_api_key


def test_defaults_match_challenge_stack() -> None:
    settings = load_settings(env_path=Path("definitely-not-a-real-env-file"))
    assert settings.stt_model == "prisma-v2.5"
    assert settings.tts_model == "timbre-v2.5"
    assert settings.tts_voice == ""  # resolved per language by remo.lang
    assert settings.language == "hi-IN"
    assert settings.stt_url == "https://api.vachana.ai/stt/v3"


def test_dotenv_file_is_loaded(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n\nGNANI_API_KEY=test-key-123\nREMO_LANG=hi-IN\n", encoding="utf-8"
    )
    # Explicit save/restore: delenv(raising=False) is a no-op when absent and
    # would let the fake key leak into later tests.
    old = os.environ.pop("GNANI_API_KEY", None)
    try:
        settings = load_settings(env_path=env_file)
        assert settings.gnani_api_key == "test-key-123"
    finally:
        os.environ.pop("GNANI_API_KEY", None)
        if old is not None:
            os.environ["GNANI_API_KEY"] = old


def test_environment_beats_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GNANI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("GNANI_API_KEY", "from-env")
    assert load_settings(env_path=env_file).gnani_api_key == "from-env"


def test_missing_key_raises_with_help() -> None:
    with pytest.raises(RuntimeError, match="app.gnani.ai/voice"):
        require_api_key(Settings(gnani_api_key=""))
