"""The daemon's observable behaviour on its status socket, end to end."""

import asyncio
import os
import signal
from contextlib import ExitStack
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
from evdev import InputEvent, ecodes

from whisper_anywhere.daemon import Daemon
from whisper_anywhere.recording import Recording
from whisper_anywhere.state import DaemonState, DaemonStatus, StatusServer

TIMEOUT = 5


class _GatedDevice:
    """A keyboard that emits nothing until the test opens the gate."""

    def __init__(self, events: list, gate: asyncio.Event) -> None:
        self._events = events
        self._gate = gate

    async def async_read_loop(self) -> AsyncGenerator[MagicMock, None]:
        await self._gate.wait()
        for event in self._events:
            await asyncio.sleep(0)
            yield event
        await asyncio.sleep(3600)


class _FakeProcess:
    def __init__(self) -> None:
        self.signals: list[int] = []

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    async def wait(self) -> int:
        return 0


class _FakeEngine:
    def __init__(self, transcript: str = "hello world") -> None:
        self.transcript = transcript
        self.calls: int = 0

    def transcribe(self, path: str, language: str | None = None) -> str:
        self.calls += 1
        return self.transcript

    def __call__(self) -> "_FakeEngine":
        return self


class _FakeOutput:
    def __init__(self) -> None:
        self.emitted: list[str] = []

    async def emit(self, text: str) -> None:
        self.emitted.append(text)


class _RecordingStarter:
    def __init__(self, process: _FakeProcess) -> None:
        self._process = process

    async def __call__(self) -> Recording:
        return Recording(
            process=self._process,
            reader=asyncio.create_task(asyncio.sleep(0)),
            buffer=bytearray(b"\x00\x01" * 100),
        )


def _key(code: int, value: int) -> MagicMock:
    event: MagicMock = MagicMock(spec=InputEvent)
    event.type = ecodes.EV_KEY
    event.code = code
    event.value = value
    return event


class _Client:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def next_status(self) -> DaemonStatus:
        line: bytes = await asyncio.wait_for(self._reader.readline(), TIMEOUT)
        return DaemonStatus.decode(line)

    async def quit(self) -> None:
        self._writer.write(b'{"command": "quit"}\n')
        await self._writer.drain()

    def close(self) -> None:
        self._writer.close()


class _Running:
    """A daemon started against a real status socket on a temporary path."""

    def __init__(self, path: Path, events: list) -> None:
        self.path = path
        self.server = StatusServer(str(path))
        self.process = _FakeProcess()
        self.engine = _FakeEngine()
        self.output = _FakeOutput()
        self.gate = asyncio.Event()
        self.events = events

    async def __aenter__(self) -> "_Running":
        self._patches = ExitStack()
        self._patches.enter_context(
            patch(
                "whisper_anywhere.keyboard.Keyboard.find_keyboards",
                return_value=[_GatedDevice(self.events, self.gate)],
            )
        )
        self._patches.enter_context(
            patch(
                "whisper_anywhere.recording.Recorder.start",
                _RecordingStarter(self.process),
            )
        )
        daemon = Daemon(None, lambda: self.engine, self.output, None, self.server)
        self.task = asyncio.create_task(daemon.run())
        self.client = await self._connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.client.close()
        try:
            await asyncio.wait_for(self.task, TIMEOUT)
        finally:
            self._patches.close()

    async def _connect(self) -> _Client:
        for _ in range(200):
            if os.path.exists(self.path):
                try:
                    reader, writer = await asyncio.open_unix_connection(self.path)
                    return _Client(reader, writer)
                except OSError:
                    pass
            await asyncio.sleep(0.01)
        raise AssertionError("the daemon never bound its status socket")


Running = _Running


def _combo_press_and_release() -> list:
    return [
        _key(ecodes.KEY_LEFTCTRL, 1),
        _key(ecodes.KEY_LEFTMETA, 1),
        _key(ecodes.KEY_SPACE, 1),
        _key(ecodes.KEY_LEFTCTRL, 0),
    ]


@pytest.mark.asyncio
class TestDictationOverTheSocket:
    async def test_one_dictation_publishes_recording_processing_idle(
        self, tmp_path: Path
    ) -> None:
        async with Running(tmp_path / "state.sock", _combo_press_and_release()) as run:
            assert (await run.client.next_status()).state == DaemonState.IDLE

            run.gate.set()

            assert (await run.client.next_status()).state == DaemonState.RECORDING
            assert (await run.client.next_status()).state == DaemonState.PROCESSING
            final: DaemonStatus = await run.client.next_status()
            assert final == DaemonStatus(DaemonState.IDLE)
            assert run.output.emitted == ["hello world"]
            assert run.engine.calls == 1

            await run.client.quit()

    async def test_a_blank_transcript_ends_idle_without_a_note(
        self, tmp_path: Path
    ) -> None:
        async with Running(tmp_path / "state.sock", _combo_press_and_release()) as run:
            run.engine.transcript = "   "
            assert (await run.client.next_status()).state == DaemonState.IDLE

            run.gate.set()

            assert (await run.client.next_status()).state == DaemonState.RECORDING
            assert (await run.client.next_status()).state == DaemonState.PROCESSING
            assert await run.client.next_status() == DaemonStatus(DaemonState.IDLE)
            assert run.output.emitted == []

            await run.client.quit()


@pytest.mark.asyncio
class TestQuit:
    async def test_quit_ends_the_run_and_removes_the_socket(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "state.sock"
        async with Running(path, _combo_press_and_release()) as run:
            assert (await run.client.next_status()).state == DaemonState.IDLE

            await run.client.quit()
            await asyncio.wait_for(run.task, TIMEOUT)

            assert not path.exists()
            run.client.close()

    async def test_quit_during_a_recording_discards_it(self, tmp_path: Path) -> None:
        events = [
            _key(ecodes.KEY_LEFTCTRL, 1),
            _key(ecodes.KEY_LEFTMETA, 1),
            _key(ecodes.KEY_SPACE, 1),
        ]
        async with Running(tmp_path / "state.sock", events) as run:
            assert (await run.client.next_status()).state == DaemonState.IDLE

            run.gate.set()

            assert (await run.client.next_status()).state == DaemonState.RECORDING

            await run.client.quit()
            await asyncio.wait_for(run.task, TIMEOUT)

            assert run.engine.calls == 0
            assert run.output.emitted == []
            assert run.process.signals == [signal.SIGINT]
