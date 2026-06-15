import asyncio
import json
import os
import re
import sys
import types
import wave
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import pytest
from evdev import ecodes

import whisper_anywhere.daemon as daemon
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder
from whisper_anywhere.transcribe import Transcriber
from whisper_anywhere.vad import VAD

FIXTURES: Path = Path(__file__).parent / "fixtures"


def fake_key_event(code: int, value: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


class FakeKeyboard:
    def __init__(self, events: list[types.SimpleNamespace]) -> None:
        self._events = events

    async def async_read_loop(self):  # type: ignore[misc]
        for ev in self._events:
            yield ev
            await asyncio.sleep(0)
        await asyncio.sleep(3600)


def pcm_from_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000, "fixture must be 16 kHz"
        assert w.getnchannels() == 1, "fixture must be mono"
        assert w.getsampwidth() == 2, "fixture must be s16le"
        return w.readframes(w.getnframes())


class _FakeRecorder:
    returncode: int = 0

    def send_signal(self, _sig: int) -> None:
        pass

    async def wait(self) -> int:
        return 0


async def drive_dictation(
    model: Transcriber,
    pcm: bytes,
    monkeypatch: pytest.MonkeyPatch,
    timeout: int = 30,
) -> Optional[str]:
    events: list[types.SimpleNamespace] = [
        fake_key_event(ecodes.KEY_F12, 1),
        fake_key_event(ecodes.KEY_F12, 0),
    ]
    monkeypatch.setattr(daemon, "find_keyboards", lambda: [FakeKeyboard(events)])

    async def fake_start() -> tuple[_FakeRecorder, asyncio.Task, bytearray]:
        buffer: bytearray = bytearray(pcm)
        read_task: asyncio.Task = asyncio.create_task(asyncio.sleep(0))
        return _FakeRecorder(), read_task, buffer

    monkeypatch.setattr(Recorder, "start", fake_start)

    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()

    output: TextOutput = TextOutput(True)
    original_emit = output.emit

    def capturing_emit(text: Optional[str]) -> None:
        original_emit(text)
        if not done.done():
            done.set_result(text)

    output.emit = capturing_emit  # type: ignore[assignment]

    daemon_instance: Daemon = Daemon(ecodes.KEY_F12, model, output, None, None)
    task: asyncio.Task = asyncio.create_task(daemon_instance.run())
    try:
        return await asyncio.wait_for(done, timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


class StubModel:
    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, path: str, language: Optional[str] = None) -> str:
        return self._text


class StubVAD:
    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]:
        return [(0, len(audio_bytes))] if audio_bytes else []

    def reset(self) -> None:
        pass


async def drive_dictation_live(
    model: Transcriber,
    pcm: bytes,
    vad: VAD,
    monkeypatch: pytest.MonkeyPatch,
    timeout: int = 30,
) -> Optional[str]:
    events: list[types.SimpleNamespace] = [
        fake_key_event(ecodes.KEY_F12, 1),
        fake_key_event(ecodes.KEY_F12, 0),
    ]
    monkeypatch.setattr(daemon, "find_keyboards", lambda: [FakeKeyboard(events)])

    async def fake_start() -> tuple[_FakeRecorder, asyncio.Task, bytearray]:
        buffer: bytearray = bytearray(pcm)
        read_task: asyncio.Task = asyncio.create_task(asyncio.sleep(0))
        return _FakeRecorder(), read_task, buffer

    monkeypatch.setattr(Recorder, "start", fake_start)

    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()

    output: TextOutput = TextOutput(True)
    original_emit_final = output.emit_final

    def capturing_emit_final(prev_text: str, final_text: str) -> None:
        original_emit_final(prev_text, final_text)
        if not done.done() and final_text:
            done.set_result(final_text)

    output.emit_final = capturing_emit_final  # type: ignore[assignment]

    daemon_instance: Daemon = Daemon(ecodes.KEY_F12, model, output, None, vad)
    task: asyncio.Task = asyncio.create_task(daemon_instance.run())
    try:
        return await asyncio.wait_for(done, timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_stub_e2e(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    pcm: bytes = b"\x00\x01" * 8000

    text: Optional[str] = await drive_dictation(
        StubModel("hello world"), pcm, monkeypatch
    )

    assert text == "hello world"
    out: str = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out) == {"text": "hello world"}


@pytest.mark.asyncio
async def test_stub_e2e_live_vad(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    pcm: bytes = b"\x00\x01" * 8000

    text: Optional[str] = await drive_dictation_live(
        StubModel("hello world"), pcm, StubVAD(), monkeypatch
    )

    assert text == "hello world"
    out: str = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out) == {"type": "final", "text": "hello world"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e_live_vad(monkeypatch: pytest.MonkeyPatch) -> None:
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    sys.modules.pop("faster_whisper", None)
    pytest.importorskip("faster_whisper")
    from whisper_anywhere.transcribe import FasterWhisperTranscriber

    pytest.importorskip("funasr")
    from whisper_anywhere.vad import FsmnVAD

    clips: list[Path] = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected: str = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model: FasterWhisperTranscriber = FasterWhisperTranscriber("tiny.en")
    except Exception as exc:
        pytest.skip(f"tiny.en model unavailable: {exc}")

    try:
        vad: FsmnVAD = FsmnVAD()
    except Exception as exc:
        pytest.skip(f"VAD model unavailable: {exc}")

    text: Optional[str] = await drive_dictation_live(
        model, pcm_from_wav(clips[0]), vad, monkeypatch, timeout=120
    )

    norm_expected: str = _normalize(expected)
    norm_actual: str = _normalize(text or "")
    ratio: float = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present: bool = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.75 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )


@pytest.mark.integration
def test_install_artifacts(installed_app: Optional[object]) -> None:
    if installed_app is None:
        pytest.skip("set WHISPER_E2E_INSTALL=1 to exercise install.sh/uninstall.sh")
    assert installed_app.bin.exists()
    assert installed_app.unit.exists()
    assert installed_app.config.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    sys.modules.pop("faster_whisper", None)
    pytest.importorskip("faster_whisper")
    from whisper_anywhere.transcribe import FasterWhisperTranscriber

    clips: list[Path] = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected: str = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model: FasterWhisperTranscriber = FasterWhisperTranscriber("tiny.en")
    except Exception as exc:
        pytest.skip(f"tiny.en model unavailable: {exc}")

    text: Optional[str] = await drive_dictation(
        model, pcm_from_wav(clips[0]), monkeypatch, timeout=120
    )

    norm_expected: str = _normalize(expected)
    norm_actual: str = _normalize(text or "")
    ratio: float = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present: bool = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.75 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_e2e_vosk(monkeypatch: pytest.MonkeyPatch) -> None:
    if not os.environ.get("WHISPER_E2E"):
        pytest.skip("set WHISPER_E2E=1 to run the real-model e2e")

    sys.modules.pop("vosk", None)
    pytest.importorskip("vosk")
    from whisper_anywhere.transcribe import VoskTranscriber

    clips: list[Path] = sorted(FIXTURES.glob("*.wav"))
    if not clips:
        pytest.skip("no audio fixture committed yet (see tests/fixtures/README.md)")

    expected: str = (FIXTURES / "transcript.txt").read_text().strip()

    try:
        model: VoskTranscriber = VoskTranscriber("vosk-model-small-en-us-0.15")
    except Exception as exc:
        pytest.skip(f"vosk model unavailable: {exc}")

    text: Optional[str] = await drive_dictation(
        model, pcm_from_wav(clips[0]), monkeypatch, timeout=120
    )

    norm_expected: str = _normalize(expected)
    norm_actual: str = _normalize(text or "")
    ratio: float = SequenceMatcher(None, norm_expected, norm_actual).ratio()
    keywords_present: bool = set(norm_expected.split()) <= set(norm_actual.split())
    assert ratio >= 0.75 or keywords_present, (
        f"transcript mismatch: expected ~{norm_expected!r}, got {norm_actual!r} "
        f"(ratio={ratio:.2f})"
    )
