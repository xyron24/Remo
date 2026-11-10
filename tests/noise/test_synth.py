"""Noise synth math: overlays, SNR targeting, WER, chart."""
import math
import struct

from tests.noise.synth import chart_svg, overlay, wer


def _tone(seconds: float = 1.0, rate: int = 16000, freq: float = 220.0) -> bytes:
    samples = [
        int(10000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(int(seconds * rate))
    ]
    return struct.pack(f"<{len(samples)}h", *samples)


def test_overlay_preserves_length_and_is_deterministic() -> None:
    pcm = _tone()
    first = overlay(pcm, "white", 5.0)
    assert len(first) == len(pcm) and first != pcm
    assert overlay(pcm, "white", 5.0) == first
    assert overlay(pcm, "white", 5.0, seed=99) != first


def test_all_kinds_differ() -> None:
    pcm = _tone()
    outs = {overlay(pcm, kind, 10.0) for kind in ("white", "rumble", "babble")}
    assert len(outs) == 3


def test_snr_targeting_is_close() -> None:
    import struct as _struct

    pcm = _tone(seconds=2.0)
    mixed = overlay(pcm, "white", 10.0)
    clean = _struct.unpack(f"<{len(pcm) // 2}h", pcm)
    noisy = _struct.unpack(f"<{len(mixed) // 2}h", mixed)
    signal = sum(c * c for c in clean) / len(clean)
    noise = sum((n - c) ** 2 for n, c in zip(noisy, clean)) / len(clean)
    measured = 10 * math.log10(signal / noise)
    assert abs(measured - 10.0) < 1.5


def test_wer_scores() -> None:
    assert wer("a b c d", "a b c d") == 0.0
    assert wer("a b c d", "a x c d") == 0.25
    assert wer("a b", "") == 1.0
    assert wer("", "") == 0.0
    assert wer("Yaad Rakhna, maths!", "yaad rakhna maths") == 0.0


def test_chart_marks_labels_and_values() -> None:
    svg = chart_svg([("clean-16k", 0.02), ("white-5db", 0.31)])
    assert svg.startswith("<svg") and "clean-16k" in svg and "white-5db" in svg
    assert "31.0%" in svg
