"""Audio framing: fixed-size frames, silence tails, WAV reading."""
import struct
import wave
from pathlib import Path

import pytest

from remo.capture.audio import (
    FRAME_BYTES,
    downsample_mono16,
    iter_frames,
    read_wav_mono16,
    silence_tail,
)


def test_frames_are_fixed_size_and_padded() -> None:
    frames = list(iter_frames(b"\x01" * 2500))
    assert len(frames) == 3
    assert all(len(f) == FRAME_BYTES for f in frames)
    assert frames[0] == b"\x01" * FRAME_BYTES
    assert frames[2] == b"\x01" * 452 + b"\x00" * (FRAME_BYTES - 452)


def test_silence_tail_length() -> None:
    assert silence_tail(500, 16000) == b"\x00" * 16000
    assert silence_tail(0, 16000) == b""


def test_downsample_integer_ratio() -> None:
    pcm48 = struct.pack("<6h", 0, 1, 2, 3, 4, 5)
    assert downsample_mono16(pcm48, 48000, 16000) == struct.pack("<2h", 0, 3)
    assert downsample_mono16(pcm48, 16000, 16000) == pcm48
    with pytest.raises(ValueError, match="integer ratios"):
        downsample_mono16(pcm48, 44100, 16000)


def test_read_mono16_wav(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    samples = [1000, -1000, 0, 500]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<4h", *samples))
    assert read_wav_mono16(path, 16000) == struct.pack("<4h", *samples)


def test_read_stereo_wav_averages_to_mono(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<4h", 1000, 3000, -1000, -3000))
    assert read_wav_mono16(path, 16000) == struct.pack("<2h", 2000, -2000)


def test_wrong_sample_rate_refuses(tmp_path: Path) -> None:
    path = tmp_path / "fast.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(struct.pack("<2h", 0, 0))
    with pytest.raises(ValueError, match="no resampling"):
        read_wav_mono16(path, 16000)
