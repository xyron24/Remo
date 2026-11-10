"""Voice probe: synthesize + transcribe one sample per locale, report.

Needs GNANI_API_KEY. Saves listenable wavs to out/ so a human judges voice
quality by ear; prints the STT round-trip for a quick text check.

Usage:
    python scripts/probe_voices.py [--langs hi-IN mr-IN]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from remo.config import Settings, load_settings
from remo.log import get_logger
from remo.stt import transcribe_file_rest
from remo.tts import synthesize

log = get_logger("probe_voices")

SAMPLES = {
    "hi-IN": "नमस्ते, मैं रेमो हूँ। याद रखना, गणित में काम बाकी है।",
    "mr-IN": "नमस्कार, मी रेमो आहे. लक्षात ठेव, गणितात काम बाकी आहे.",
}


def probe(code: str, base: Settings) -> dict[str, str]:
    if code not in SAMPLES:
        raise ValueError(f"no sample for {code} (have: {sorted(SAMPLES)})")
    settings = Settings(
        gnani_api_key=base.gnani_api_key,
        github_token=base.github_token,
        stt_url=base.stt_url,
        stt_stream_url=base.stt_stream_url,
        stt_model=base.stt_model,
        tts_url=base.tts_url,
        tts_model=base.tts_model,
        tts_voice="",
        language=code,
    )
    out = Path("out") / f"probe-{code}.wav"
    synthesize(SAMPLES[code], settings=settings, out=out)
    transcript = transcribe_file_rest(out, code)
    return {"locale": code, "wav": str(out), "bytes": str(out.stat().st_size), "transcript": transcript}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Gnani voices per locale.")
    parser.add_argument("--langs", nargs="+", default=["hi-IN", "mr-IN"])
    args = parser.parse_args()
    base = load_settings()
    failed = 0
    for code in args.langs:
        try:
            report = probe(code, base)
            log.info("%s: %s bytes -> %s", report["locale"], report["bytes"], report["transcript"])
        except Exception as exc:  # noqa: BLE001 - probe reports per-locale and continues
            log.error("%s FAILED: %s", code, exc)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
