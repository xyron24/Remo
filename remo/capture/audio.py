"""Audio framing helpers for Gnani Prisma streaming.

Prisma expects raw 16-bit mono PCM in fixed-size binary frames. This module
only reshapes bytes; it records nothing and resamples nothing.
"""
from __future__ import annotations

import struct
import wave
from collections.abc import Iterator
from pathlib import Path

FRAME_BYTES = 1024


def iter_frames(pcm: bytes, frame_size: int = FRAME_BYTES) -> Iterator[bytes]:
    """Yield fixed-size frames, zero-padding the final partial frame."""
    for offset in range(0, len(pcm), frame_size):
        frame = pcm[offset : offset + frame_size]
        if len(frame) < frame_size:
            frame += b"\x00" * (frame_size - len(frame))
        yield frame


def silence_tail(duration_ms: int, sample_rate_hz: int) -> bytes:
    """Zeros (digital silence) for 16-bit mono audio; closes a segment."""
    samples = max(0, int(sample_rate_hz * duration_ms / 1000))
    return b"\x00" * (samples * 2)


def downsample_mono16(pcm: bytes, from_rate: int, to_rate: int) -> bytes:
    """Naive integer-ratio downsampling (decimation) for 16-bit mono PCM."""
    if from_rate == to_rate:
        return pcm
    if from_rate % to_rate != 0:
        raise ValueError(f"only integer ratios supported: {from_rate} -> {to_rate}")
    factor = from_rate // to_rate
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    return struct.pack(f"<{len(samples[::factor])}h", *samples[::factor])


def read_wav_mono16(path: Path, expected_rate: int) -> bytes:
    """Read a WAV file as 16-bit mono PCM. Stereo is averaged; 8-bit scaled.

    Raises ValueError when the sample rate differs , resampling is out of scope.
    """
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if rate != expected_rate:
        raise ValueError(f"{path} is {rate} Hz, need {expected_rate} Hz (no resampling yet)")
    if width == 1:  # unsigned 8-bit -> signed 16-bit
        samples = [(b - 128) * 256 for b in raw]
    elif width == 2:
        samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    else:
        raise ValueError(f"unsupported sample width: {width} bytes")
    if channels == 2:
        samples = [(a + b) // 2 for a, b in zip(samples[::2], samples[1::2])]
    elif channels != 1:
        raise ValueError(f"unsupported channel count: {channels}")
    return struct.pack(f"<{len(samples)}h", *samples)
