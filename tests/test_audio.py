import struct
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from whisper_anywhere.audio import (
    AUDIO,
    SAMPLE_RATE,
    read_audio,
    stop_recording,
    write_wav,
)


class TestWriteWav:
    def test_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), b"")
            assert path.exists()
            assert path.stat().st_size > 0

    def test_riff_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), b"\x00" * 100)
            data: bytes = path.read_bytes()
            assert data[:4] == b"RIFF"
            assert data[8:12] == b"WAVE"

    def test_fmt_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), b"\x00" * 100)
            data: bytes = path.read_bytes()
            fmt: bytes = data[12:36]
            assert fmt[:4] == b"fmt "
            chunk_size: int = struct.unpack("<I", fmt[4:8])[0]
            assert chunk_size == 16
            audio_format: int = struct.unpack("<H", fmt[8:10])[0]
            assert audio_format == 1
            channels: int = struct.unpack("<H", fmt[10:12])[0]
            assert channels == 1
            sample_rate: int = struct.unpack("<I", fmt[12:16])[0]
            assert sample_rate == SAMPLE_RATE

    def test_data_chunk_size(self) -> None:
        payload: bytes = b"\x00" * 500
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), payload)
            data: bytes = path.read_bytes()
            riff_size: int = struct.unpack("<I", data[4:8])[0]
            assert riff_size == 36 + len(payload)
            data_chunk: bytes = data[36:]
            assert data_chunk[:4] == b"data"
            data_size: int = struct.unpack("<I", data_chunk[4:8])[0]
            assert data_size == len(payload)
            assert data_chunk[8:] == payload

    def test_custom_params(self) -> None:
        payload: bytes = b"\x00" * 200
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), payload, sample_rate=44100, sample_width=2, channels=2)
            data: bytes = path.read_bytes()
            fmt: bytes = data[12:36]
            channels: int = struct.unpack("<H", fmt[10:12])[0]
            assert channels == 2
            sample_rate: int = struct.unpack("<I", fmt[12:16])[0]
            assert sample_rate == 44100

    def test_roundtrip_larger_file(self) -> None:
        payload: bytes = bytes(range(256)) * 100
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), payload)
            data: bytes = path.read_bytes()
            header_size: int = 44
            assert data[header_size:] == payload

    def test_empty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "test.wav"
            write_wav(str(path), b"")
            data: bytes = path.read_bytes()
            assert len(data) == 44


@pytest.mark.asyncio
async def test_read_audio() -> None:
    proc: AsyncMock = AsyncMock()
    proc.stdout.read.side_effect = [b"hello ", b"world", b""]
    buffer: bytearray = bytearray()
    await read_audio(proc, buffer)
    assert buffer == bytearray(b"hello world")


@pytest.mark.asyncio
async def test_read_audio_empty() -> None:
    proc: AsyncMock = AsyncMock()
    proc.stdout.read.side_effect = [b""]
    buffer: bytearray = bytearray()
    await read_audio(proc, buffer)
    assert buffer == bytearray()


@pytest.mark.asyncio
async def test_read_audio_large_chunks() -> None:
    chunk: bytes = b"x" * 8192
    proc: AsyncMock = AsyncMock()
    proc.stdout.read.side_effect = [chunk, chunk, b""]
    buffer: bytearray = bytearray()
    await read_audio(proc, buffer)
    assert len(buffer) == 16384
    assert buffer == bytearray(chunk * 2)


@pytest.mark.asyncio
async def test_read_audio_caps_at_max(monkeypatch: Any) -> None:
    from whisper_anywhere import audio

    monkeypatch.setattr(audio, "MAX_RECORDING_BYTES", 8)
    proc: AsyncMock = AsyncMock()
    proc.send_signal = MagicMock()
    proc.stdout.read.side_effect = [b"xxxx", b"xxxx", b"xxxx", b""]
    buffer: bytearray = bytearray()
    await audio.read_audio(proc, buffer)
    # Cap reached after 8 bytes: parec is stopped and reading stops early.
    proc.send_signal.assert_called_once()
    assert len(buffer) == 8


def test_stop_recording_ignores_dead_process() -> None:
    proc: MagicMock = MagicMock()
    proc.send_signal.side_effect = ProcessLookupError()
    stop_recording(proc)  # must not raise


def test_audio_constants() -> None:
    # Lives in a per-user runtime dir, not world-writable /tmp.
    assert AUDIO.endswith("audio.wav")
    assert "whisper-anywhere" in AUDIO
    assert SAMPLE_RATE == 16000
