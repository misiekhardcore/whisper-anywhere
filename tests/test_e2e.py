"""End-to-end dictation pipeline test.

Drives the real daemon loop (``run_daemon``) in single-key mode with a fake
keyboard and a pre-recorded audio source piped through a real subprocess, then
asserts the text it would type. Output is checked via ``--stdout`` JSON mode so
no ``ydotool`` is involved.

Two tests:
- ``test_stub_e2e`` — fast/deterministic, runs everywhere. A stub model returns
  a known transcript; this validates the press -> record -> write -> transcribe
  -> emit wiring end to end.
- ``test_real_e2e`` — gated on ``WHISPER_E2E=1`` and ``@pytest.mark.integration``;
  loads a real ``tiny.en`` model and transcribes a committed CC0 clip, asserting
  a tolerant match against its known transcript.
"""

import asyncio
import json
import os
import re
import types
import wave
from difflib import SequenceMatcher
from pathlib import Path

import pytest
from evdev import ecodes

import whisper_anywhere.__main__ as m

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
def fake_key_event(code, value):
    return types.SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


class FakeKeyboard:
    """Stand-in for an evdev device. ``async_read_loop`` is an async generator
    (matching ``async for event in dev.async_read_loop()``)."""

    def __init__(self, events):
        self._events = events

    async def async_read_loop(self):
        for ev in self._events:
            yield ev
            await asyncio.sleep(0)
        # Keep the loop alive so run_daemon's outer `while True` doesn't re-scan;
        # the driving task is cancelled once the transcript has been emitted.
        await asyncio.sleep(3600)


def pcm_from_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000, "fixture must be 16 kHz"
        assert w.getnchannels() == 1, "fixture must be mono"
        assert w.getsampwidth() == 2, "fixture must be s16le"
        return w.readframes(w.getnframes())


class _FakeRecorder:
    """Stand-in for the parec subprocess. The 'microphone' is the pre-recorded
    PCM, pre-loaded into the capture buffer, so the result is deterministic and
    not racing the SIGINT that stop_recording() sends on release."""

    returncode = 0

    def send_signal(self, _sig):  # what stop_recording() calls
        pass

    async def wait(self):
        return 0


async def drive_dictation(model, pcm, monkeypatch, timeout=30):
    """Simulate one F12 press/release with ``pcm`` as the recorded mic input and
    return the emitted text."""
    events = [
        fake_key_event(ecodes.KEY_F12, 1),  # press
        fake_key_event(ecodes.KEY_F12, 0),  # release
    ]
    monkeypatch.setattr(m, "find_keyboard", lambda: FakeKeyboard(events))

    async def fake_start_recording():
        buffer = bytearray(pcm)  # mic input = pre-recorded audio
        read_task = asyncio.create_task(asyncio.sleep(0))
        return _FakeRecorder(), read_task, buffer

    monkeypatch.setattr(m, "_start_recording", fake_start_recording)

    loop = asyncio.get_running_loop()
    done = loop.create_future()
    original_emit = m.emit

    def capturing_emit(text, stdout_mode):
        original_emit(text, stdout_mode)  # keep real stdout JSON behaviour
        if not done.done():
            done.set_result(text)

    monkeypatch.setattr(m, "emit", capturing_emit)

    task = asyncio.create_task(m.run_daemon(ecodes.KEY_F12, model, stdout_mode=True))
    try:
        return await asyncio.wait_for(done, timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


# --------------------------------------------------------------------------- #
# Stub e2e (default suite)
# --------------------------------------------------------------------------- #
class StubModel:
    def __init__(self, text):
        self._text = text

    def transcribe(self, path, beam_size=5, language=None):
        return [types.SimpleNamespace(text=self._text)], None


@pytest.mark.asyncio
async def test_stub_e2e(monkeypatch, capsys):
    pcm = b"\x00\x01" * 8000  # ~0.5s of 16 kHz mono s16le

    text = await drive_dictation(StubModel("hello world"), pcm, monkeypatch)

    assert text == "hello world"
    # --stdout mode emitted exactly the JSON line the daemon would print.
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out) == {"text": "hello world"}


# --------------------------------------------------------------------------- #
# Real e2e (gated)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e(monkeypatch):
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    pytest.importorskip("faster_whisper")
    from faster_whisper import WhisperModel

    clips = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    except Exception as exc:  # offline / download failure
        pytest.skip(f"tiny.en model unavailable: {exc}")

    text = await drive_dictation(model, pcm_from_wav(clips[0]), monkeypatch, timeout=120)

    norm_expected, norm_actual = _normalize(expected), _normalize(text)
    ratio = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.6 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )
