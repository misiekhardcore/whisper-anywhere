import asyncio
import json
import os
import re
import sys
import types
import wave
from difflib import SequenceMatcher
from pathlib import Path

import pytest
from evdev import ecodes

import whisper_anywhere.daemon as daemon
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder

FIXTURES = Path(__file__).parent / "fixtures"


def fake_key_event(code, value):
    return types.SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


class FakeKeyboard:
    def __init__(self, events):
        self._events = events

    async def async_read_loop(self):
        for ev in self._events:
            yield ev
            await asyncio.sleep(0)
        await asyncio.sleep(3600)


def pcm_from_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000, "fixture must be 16 kHz"
        assert w.getnchannels() == 1, "fixture must be mono"
        assert w.getsampwidth() == 2, "fixture must be s16le"
        return w.readframes(w.getnframes())


class _FakeRecorder:
    returncode = 0

    def send_signal(self, _sig):
        pass

    async def wait(self):
        return 0


async def drive_dictation(model, pcm, monkeypatch, timeout=30):
    events = [
        fake_key_event(ecodes.KEY_F12, 1),
        fake_key_event(ecodes.KEY_F12, 0),
    ]
    monkeypatch.setattr(daemon, "find_keyboards", lambda: [FakeKeyboard(events)])

    async def fake_start():
        buffer = bytearray(pcm)
        read_task = asyncio.create_task(asyncio.sleep(0))
        return _FakeRecorder(), read_task, buffer

    monkeypatch.setattr(Recorder, "start", fake_start)

    loop = asyncio.get_running_loop()
    done = loop.create_future()

    output = TextOutput(True)
    original_emit = output.emit

    def capturing_emit(text):
        original_emit(text)
        if not done.done():
            done.set_result(text)

    output.emit = capturing_emit

    daemon_instance = Daemon(ecodes.KEY_F12, model, output, None, None)
    task = asyncio.create_task(daemon_instance.run())
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


class StubModel:
    def __init__(self, text):
        self._text = text

    def transcribe(self, path, language=None):
        return self._text


class StubVAD:
    def detect(self, audio_bytes, sample_rate):
        return [(0, len(audio_bytes))] if audio_bytes else []

    def reset(self):
        pass


async def drive_dictation_live(model, pcm, vad, monkeypatch, timeout=30):
    events = [
        fake_key_event(ecodes.KEY_F12, 1),
        fake_key_event(ecodes.KEY_F12, 0),
    ]
    monkeypatch.setattr(daemon, "find_keyboards", lambda: [FakeKeyboard(events)])

    async def fake_start():
        buffer = bytearray(pcm)
        read_task = asyncio.create_task(asyncio.sleep(0))
        return _FakeRecorder(), read_task, buffer

    monkeypatch.setattr(Recorder, "start", fake_start)

    loop = asyncio.get_running_loop()
    done = loop.create_future()

    output = TextOutput(True)
    original_emit_final = output.emit_final

    def capturing_emit_final(prev_text, final_text):
        original_emit_final(prev_text, final_text)
        if not done.done() and final_text:
            done.set_result(final_text)

    output.emit_final = capturing_emit_final

    daemon_instance = Daemon(ecodes.KEY_F12, model, output, None, vad)
    task = asyncio.create_task(daemon_instance.run())
    try:
        return await asyncio.wait_for(done, timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_stub_e2e(monkeypatch, capsys):
    pcm = b"\x00\x01" * 8000

    text = await drive_dictation(StubModel("hello world"), pcm, monkeypatch)

    assert text == "hello world"
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out) == {"text": "hello world"}


@pytest.mark.asyncio
async def test_stub_e2e_live_vad(monkeypatch, capsys):
    pcm = b"\x00\x01" * 8000

    text = await drive_dictation_live(
        StubModel("hello world"), pcm, StubVAD(), monkeypatch
    )

    assert text == "hello world"
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out) == {"type": "final", "text": "hello world"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e_live_vad(monkeypatch):
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    sys.modules.pop("faster_whisper", None)
    pytest.importorskip("faster_whisper")
    from whisper_anywhere.transcribe import FasterWhisperTranscriber

    pytest.importorskip("funasr")
    from whisper_anywhere.vad import FsmnVAD

    clips = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model = FasterWhisperTranscriber("tiny.en")
    except Exception as exc:
        pytest.skip(f"tiny.en model unavailable: {exc}")

    try:
        vad = FsmnVAD()
    except Exception as exc:
        pytest.skip(f"VAD model unavailable: {exc}")

    text = await drive_dictation_live(
        model, pcm_from_wav(clips[0]), vad, monkeypatch, timeout=120
    )

    norm_expected, norm_actual = _normalize(expected), _normalize(text)
    ratio = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.75 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )


@pytest.mark.integration
def test_install_artifacts(installed_app):
    if installed_app is None:
        pytest.skip("set WHISPER_E2E_INSTALL=1 to exercise install.sh/uninstall.sh")
    assert installed_app.bin.exists()
    assert installed_app.unit.exists()
    assert installed_app.config.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e(monkeypatch):
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    sys.modules.pop("faster_whisper", None)
    pytest.importorskip("faster_whisper")
    from whisper_anywhere.transcribe import FasterWhisperTranscriber

    clips = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model = FasterWhisperTranscriber("tiny.en")
    except Exception as exc:
        pytest.skip(f"tiny.en model unavailable: {exc}")

    text = await drive_dictation(
        model, pcm_from_wav(clips[0]), monkeypatch, timeout=120
    )

    norm_expected, norm_actual = _normalize(expected), _normalize(text)
    ratio = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.75 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )
