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

from remo.log import get_logger
from remo.tts import synthesize

log = get_logger("smoke_timbre")

DEFAULT_TEXT = "नमस्ते, मैं रेमो हूँ।"


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize speech via Gnani Timbre.")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out", default="out/hello.wav")
    args = parser.parse_args()

    try:
        out_path = synthesize(args.text, out=Path(args.out))
        size = out_path.stat().st_size
    except Exception as exc:  # noqa: BLE001 - smoke script reports and exits nonzero
        log.error("Timbre smoke test FAILED: %s", exc)
        return 1
    log.info("Timbre smoke test PASSED. Wrote %s (%d bytes).", out_path, size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
