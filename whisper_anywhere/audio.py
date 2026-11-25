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
DEFAULT_MAX_RECORDING_SECONDS = 300

# Per-user runtime dir (0700) instead of world-writable /tmp.
AUDIO = os.path.join(Config.runtime_dir(), "audio.wav")


def recording_bytes(seconds: float) -> int:
    return int(SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * seconds)


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


async def read_audio(
    proc: "asyncio.subprocess.Process",
    buffer: bytearray,
    max_bytes: int | None = None,
    cap_reached: "asyncio.Event | None" = None,
) -> None:
    """Collect PCM until parec exits, stopping it once max_bytes is reached.

    The flushed tail after the stop is still drained, so no buffered speech is
    lost. cap_reached lets the daemon transcribe at the cap instead of waiting
    for a release that may never come.
    """
    limit = (
        recording_bytes(DEFAULT_MAX_RECORDING_SECONDS)
        if max_bytes is None
        else max_bytes
    )
    capped = False
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buffer.extend(chunk)
        if not capped and len(buffer) >= limit:
            capped = True
            stop_recording(proc)
            if cap_reached is not None:
                cap_reached.set()
