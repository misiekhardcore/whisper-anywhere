import asyncio
import os
import signal
import wave

from .config import Config

# Fixed requirements for whisper.cpp input — not device-native parameters.
# parec is told to convert to this format regardless of the microphone's native rate.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # s16le = 2 bytes per sample
CHANNELS = 1
PAREC_FORMAT = "s16le"
PAREC_LATENCY_MS = 30

# Cap a single recording so a stuck/held hotkey can't run parec forever.
MAX_RECORDING_SECONDS = 60
MAX_RECORDING_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * MAX_RECORDING_SECONDS

# Per-user runtime dir (0700) instead of world-writable /tmp.
AUDIO = os.path.join(Config.runtime_dir(), "audio.wav")


def stop_recording(proc: "asyncio.subprocess.Process | None") -> None:
    """SIGINT parec so it flushes its buffer; safe to call more than once."""
    try:
        proc.send_signal(signal.SIGINT)
    except ProcessLookupError:
        pass


def write_wav(
    path: str,
    data: bytes,
    sample_rate: int = SAMPLE_RATE,
    sample_width: int = SAMPLE_WIDTH,
    channels: int = CHANNELS,
) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(data)


async def read_audio(proc: "asyncio.subprocess.Process", buffer: bytearray) -> None:
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) >= MAX_RECORDING_BYTES:
            stop_recording(proc)
            break
