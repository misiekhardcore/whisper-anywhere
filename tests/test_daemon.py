import asyncio
from typing import Any
from unittest.mock import patch

from evdev import ecodes

import whisper_anywhere.daemon as daemon_module
from tests.helpers import _async_mock, _FakeDevice, _key_event, _MockVAD
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.output import TextOutput


class TestRunDaemonMultiKeyboard:
    def test_hotkey_on_any_keyboard_triggers_recording(self) -> None:
        idle_keyboard: _FakeDevice = _FakeDevice([])
        used_keyboard: _FakeDevice = _FakeDevice(
            [
                _key_event(ecodes.KEY_LEFTCTRL, 1),
                _key_event(ecodes.KEY_LEFTMETA, 1),
                _key_event(ecodes.KEY_SPACE, 1),
                _key_event(ecodes.KEY_SPACE, 0),
            ]
        )
        starts: int = 0
        emitted: list[str] = []

        async def fake_start() -> tuple[Any, asyncio.Task, bytearray]:
            nonlocal starts
            starts += 1
            return (
                _async_mock(),
                asyncio.create_task(asyncio.sleep(0)),
                bytearray(b"test"),
            )

        async def fake_finish(
            self: Any,
            proc: Any,
            read_task: Any,
            buffer: Any,
            *,
            vad_task: Any = None,
            stop_vad: Any = None,
        ) -> None:
            emitted.append("transcribed text")

        async def scenario() -> None:
            daemon: Daemon = Daemon(None, None, TextOutput(False), None, None)
            task: asyncio.Task = asyncio.create_task(daemon.run())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch.object(
                daemon_module,
                "find_keyboards",
                return_value=[idle_keyboard, used_keyboard],
            ),
            patch("whisper_anywhere.recording.Recorder.start", fake_start),
            patch("whisper_anywhere.recording.Recorder.finish", fake_finish),
            patch.object(daemon_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        assert emitted == ["transcribed text"]


class TestRunDaemonLiveMode:
    def test_live_mode_starts_vad_task(self) -> None:
        keyboard: _FakeDevice = _FakeDevice(
            [
                _key_event(ecodes.KEY_LEFTCTRL, 1),
                _key_event(ecodes.KEY_LEFTMETA, 1),
                _key_event(ecodes.KEY_SPACE, 1),
                _key_event(ecodes.KEY_SPACE, 0),
            ]
        )
        starts: int = 0

        async def fake_start() -> tuple[str, str, str]:
            nonlocal starts
            starts += 1
            return ("proc", "read_task", "buffer")

        async def scenario() -> None:
            daemon: Daemon = Daemon(None, None, TextOutput(False), None, _MockVAD())
            task: asyncio.Task = asyncio.create_task(daemon.run())
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch.object(daemon_module, "find_keyboards", return_value=[keyboard]),
            patch("whisper_anywhere.recording.Recorder.start", fake_start),
            patch("whisper_anywhere.recording.Recorder.finish") as mock_finish,
            patch.object(daemon_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        mock_finish.assert_awaited_once()
