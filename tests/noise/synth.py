"""Synthetic telephony-noise overlays + scoring for the noise benchmark.

Pure standard library, deterministic (seeded): white hiss (fan), low rumble
(traffic), and babble (delayed self-mix as crowd murmur). Honest labeling:
these are synthetic stand-ins until field recordings land in fixtures/.
"""
from __future__ import annotations

import math
import random
import re
import struct

KINDS = ("white", "rumble", "babble")


def _to_samples(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


def _from_samples(samples: list[float]) -> bytes:
    clipped = [max(-32768, min(32767, int(round(v)))) for v in samples]
    return struct.pack(f"<{len(clipped)}h", *clipped)


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / max(1, len(values)))


def _white(count: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) for _ in range(count)]


def _rumble(count: int, rate: int, rng: random.Random) -> list[float]:
    """Lowpassed noise (traffic-like): moving average over white."""
    raw = _white(count, rng)
    window = max(8, rate // 200)
    out: list[float] = []
    running = 0.0
    for i, value in enumerate(raw):
        running += value
        if i >= window:
            running -= raw[i - window]
        out.append(running / min(i + 1, window) * 2.0)
    return out


def _babble(clean: list[int], rate: int) -> list[float]:
    """Crowd-murmur stand-in: attenuated delayed self-copies."""
    out = [0.0] * len(clean)
    for delay_s, gain in ((0.23, 0.30), (0.47, 0.22), (0.71, 0.15)):
        delay = int(delay_s * rate)
        for i in range(delay, len(clean)):
            out[i] += clean[i - delay] / 32768.0 * gain
    return out


def overlay(pcm: bytes, kind: str, snr_db: float, rate: int = 16000, seed: int = 7) -> bytes:
    """Mix `kind` of noise over clean PCM at the target signal-to-noise ratio."""
    if kind not in KINDS:
        raise ValueError(f"unknown noise kind: {kind} (want one of {KINDS})")
    clean = _to_samples(pcm)
    rng = random.Random(seed)
    if kind == "white":
        noise = _white(len(clean), rng)
    elif kind == "rumble":
        noise = _rumble(len(clean), rate, rng)
    else:
        noise = _babble(clean, rate)
    clean_rms = _rms([float(v) for v in clean]) or 1.0
    noise_rms = _rms(noise) or 1.0
    scale = (clean_rms / (10.0 ** (snr_db / 20.0))) / noise_rms
    return _from_samples([c + n * scale for c, n in zip(clean, noise)])


def _words(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\u0900-\u097F ]", "", text.lower())
    return cleaned.split()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: word-level edits over reference length (lower better)."""
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        cur = [i]
        for j in range(1, len(hyp) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref[i - 1] != hyp[j - 1])))
        prev = cur
    return prev[-1] / len(ref)


def chart_svg(rows: list[tuple[str, float]], title: str = "Mean WER by condition") -> str:
    """Small olive bar chart (no dependencies) for the benchmark report."""
    width, left, bar_h, gap = 640, 220, 22, 12
    height = 60 + len(rows) * (bar_h + gap)
    worst = max([value for _, value in rows] + [0.01])
    bars = []
    for i, (label, value) in enumerate(rows):
        y = 44 + i * (bar_h + gap)
        w = max(2.0, (width - left - 70) * (value / worst))
        bars.append(
            f'<text x="8" y="{y + 16}" font-size="13" fill="#1F2421">{label}</text>'
            f'<rect x="{left}" y="{y}" width="{w:.0f}" height="{bar_h}" rx="4" fill="#4F5B3A"/>'
            f'<text x="{left + w + 8:.0f}" y="{y + 16}" font-size="13" fill="#1F2421">{value:.1%}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img">'
        f'<rect width="{width}" height="{height}" fill="#F5F5F0"/>'
        f'<text x="8" y="24" font-size="15" font-weight="bold" fill="#1F2421">{title}</text>'
        + "".join(bars) + "</svg>"
    )
