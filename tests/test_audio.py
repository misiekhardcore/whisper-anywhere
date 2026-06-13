import struct
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from whisper_anywhere.audio import (
    write_wav,
    read_audio,
    stop_recording,
    AUDIO,
    SAMPLE_RATE,
)


class TestWriteWav:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), b"")
            assert path.exists()
            assert path.stat().st_size > 0

    def test_riff_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), b"\x00" * 100)
            data = path.read_bytes()
            assert data[:4] == b"RIFF"
            assert data[8:12] == b"WAVE"

    def test_fmt_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), b"\x00" * 100)
            data = path.read_bytes()
            fmt = data[12:36]
            assert fmt[:4] == b"fmt "
            chunk_size = struct.unpack("<I", fmt[4:8])[0]
            assert chunk_size == 16
            audio_format = struct.unpack("<H", fmt[8:10])[0]
            assert audio_format == 1
            channels = struct.unpack("<H", fmt[10:12])[0]
            assert channels == 1
            sample_rate = struct.unpack("<I", fmt[12:16])[0]
            assert sample_rate == SAMPLE_RATE

    def test_data_chunk_size(self):
        payload = b"\x00" * 500
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), payload)
            data = path.read_bytes()
            riff_size = struct.unpack("<I", data[4:8])[0]
            assert riff_size == 36 + len(payload)
            data_chunk = data[36:]
            assert data_chunk[:4] == b"data"
            data_size = struct.unpack("<I", data_chunk[4:8])[0]
            assert data_size == len(payload)
            assert data_chunk[8:] == payload

    def test_custom_params(self):
        payload = b"\x00" * 200
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), payload, sample_rate=44100, sample_width=2, channels=2)
            data = path.read_bytes()
            fmt = data[12:36]
            channels = struct.unpack("<H", fmt[10:12])[0]
            assert channels == 2
            sample_rate = struct.unpack("<I", fmt[12:16])[0]
            assert sample_rate == 44100

    def test_roundtrip_larger_file(self):
        payload = bytes(range(256)) * 100
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), payload)
            data = path.read_bytes()
            header_size = 44
            assert data[header_size:] == payload

    def test_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.wav"
            write_wav(str(path), b"")
            data = path.read_bytes()
            assert len(data) == 44


@pytest.mark.asyncio
async def test_read_audio():
    proc = AsyncMock()
    proc.stdout.read.side_effect = [b"hello ", b"world", b""]
    buffer = bytearray()
    await read_audio(proc, buffer)
    assert buffer == bytearray(b"hello world")


@pytest.mark.asyncio
async def test_read_audio_empty():
    proc = AsyncMock()
    proc.stdout.read.side_effect = [b""]
    buffer = bytearray()
    await read_audio(proc, buffer)
    assert buffer == bytearray()


@pytest.mark.asyncio
async def test_read_audio_large_chunks():
    chunk = b"x" * 8192
    proc = AsyncMock()
    proc.stdout.read.side_effect = [chunk, chunk, b""]
    buffer = bytearray()
    await read_audio(proc, buffer)
    assert len(buffer) == 16384
    assert buffer == bytearray(chunk * 2)


@pytest.mark.asyncio
async def test_read_audio_caps_at_max(monkeypatch):
    from whisper_anywhere import audio

    monkeypatch.setattr(audio, "MAX_RECORDING_BYTES", 8)
    proc = AsyncMock()
    proc.send_signal = MagicMock()
    proc.stdout.read.side_effect = [b"xxxx", b"xxxx", b"xxxx", b""]
    buffer = bytearray()
    await audio.read_audio(proc, buffer)
    # Cap reached after 8 bytes: parec is stopped and reading stops early.
    proc.send_signal.assert_called_once()
    assert len(buffer) == 8


def test_stop_recording_ignores_dead_process():
    proc = MagicMock()
    proc.send_signal.side_effect = ProcessLookupError()
    stop_recording(proc)  # must not raise


def test_audio_constants():
    # Lives in a per-user runtime dir, not world-writable /tmp.
    assert AUDIO.endswith("audio.wav")
    assert "whisper-anywhere" in AUDIO
    assert SAMPLE_RATE == 16000
