"""Noise benchmark: fixtures -> noisy conditions -> Prisma -> WER report.

First run synthesizes fixtures via Timbre (needs GNANI_API_KEY) into
tests/noise/fixtures/ — committed small wavs + refs. Re-runs reuse them.
Transcribes each condition over REST (deterministic; the app streams live),
then writes tests/noise/results.md + chart.svg.

Usage:
    python scripts/noise_bench.py [--fixtures-only]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from remo.capture.audio import downsample_mono16
from remo.config import load_settings, require_api_key
from remo.log import get_logger
from remo.stt import transcribe_file_rest
from remo.tts import synthesize
from tests.noise.synth import chart_svg, overlay, wer

log = get_logger("noise_bench")

ROOT = Path(__file__).resolve().parent.parent / "tests" / "noise"
FIX_DIR = ROOT / "fixtures"

FIXTURES = [
    ("save-maths", "याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है।",
     ["गणित", "इंटीग्रेशन", "बाकी"]),
    ("save-gsoc", "याद रखना, जीसॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी हैं।",
     ["लॉगिन", "फिक्स", "डॉक्स"]),
    ("recall-left", "गणित में क्या बचा है?",
     ["गणित", "बचा"]),
    ("remind", "कल सुबह नौ बजे चाय याद दिलाना।",
     ["सुबह", "चाय", "याद"]),
    ("quiz-maths", "गणित में क्विज़ करो।",
     ["गणित", "क्विज़"]),
]

CONDITIONS = [
    ("clean-16k", None, 16000),
    ("clean-8k", None, 8000),
    ("white-15db", ("white", 15.0), 16000),
    ("white-5db", ("white", 5.0), 16000),
    ("rumble-5db", ("rumble", 5.0), 16000),
    ("babble-5db", ("babble", 5.0), 16000),
    ("white-5db-8k", ("white", 5.0), 8000),
]


def _write_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def _read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        return wav.readframes(wav.getnframes()), wav.getframerate()


def ensure_fixtures() -> list[dict]:
    """Generate fixture wavs via Timbre once; reuse on later runs."""
    refs_path = FIX_DIR / "refs.json"
    if refs_path.exists():
        return json.loads(refs_path.read_text(encoding="utf-8"))
    settings = load_settings()
    require_api_key(settings)
    refs = []
    for clip_id, text, keywords in FIXTURES:
        out = FIX_DIR / f"{clip_id}.wav"
        synthesize(text, settings=settings, out=out)
        refs.append({"id": clip_id, "text": text, "keywords": keywords, "file": out.name})
        log.info("fixture ready: %s", out.name)
    refs_path.write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")
    return refs


def run_bench() -> list[dict]:
    refs = ensure_fixtures()
    settings = load_settings()
    rows = []
    for ref in refs:
        pcm48, rate48 = _read_wav(FIX_DIR / ref["file"])
        pcm16 = downsample_mono16(pcm48, rate48, 16000)
        for name, noise, rate in CONDITIONS:
            pcm = pcm16
            if noise:
                kind, snr = noise
                pcm = overlay(pcm, kind, snr, rate=16000)
            if rate == 8000:
                pcm = downsample_mono16(pcm, 16000, 8000)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            _write_wav(tmp_path, pcm, rate)
            try:
                transcript = transcribe_file_rest(tmp_path, settings.language)
            finally:
                tmp_path.unlink(missing_ok=True)
            score = wer(ref["text"], transcript)
            hits = sum(1 for kw in ref["keywords"] if kw in transcript)
            rows.append({
                "clip": ref["id"], "condition": name, "wer": round(score, 3),
                "keywords": f"{hits}/{len(ref['keywords'])}", "transcript": transcript,
            })
            log.info("%s/%s: WER %.3f (%s)", ref["id"], name, score, transcript[:60])
    return rows


def write_report(rows: list[dict]) -> None:
    by_condition: dict[str, list[float]] = {}
    for row in rows:
        by_condition.setdefault(row["condition"], []).append(row["wer"])
    means = [(name, sum(v) / len(v)) for name, v in by_condition.items()]
    (ROOT / "chart.svg").write_text(chart_svg(means), encoding="utf-8")
    lines = ["# Noise benchmark", "",
             "Mean WER by condition (lower is better; fixtures: Timbre Hindi, "
             "noise: synthetic overlays, 8k = telephony downsample):", "",
             "| condition | mean WER |", "|---|---|"]
    lines += [f"| {name} | {mean:.1%} |" for name, mean in means]
    lines += ["", "## Per clip", "", "| clip | condition | WER | keywords | transcript |",
              "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['clip']} | {row['condition']} | {row['wer']:.3f} "
                     f"| {row['keywords']} | {row['transcript'][:80]} |")
    (ROOT / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Prisma on noisy telephony-like audio.")
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.fixtures_only:
            ensure_fixtures()
        else:
            write_report(run_bench())
    except Exception as exc:  # noqa: BLE001 - bench script reports and exits nonzero
        log.error("noise bench FAILED: %s", exc)
        return 1
    log.info("noise bench done: tests/noise/results.md + chart.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
