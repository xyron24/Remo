"""Make the project root importable so tests can use `remo` and `scripts`."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def _no_real_llm_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-live tests never see the developer's real GEMINI_API_KEY.

    load_settings() reads .env from the repo root, so without this every turn
    test would route through real Gemini: slow, flaky, and quota-burning.
    """
    if "live" in request.keywords:
        return
    # Set-but-empty: dotenv never overrides real env, so the developer's
    # .env keys stay invisible whether they came from env or file.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
