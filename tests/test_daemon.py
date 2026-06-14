import asyncio
from unittest.mock import patch

from evdev import ecodes

import whisper_anywhere.daemon as daemon_module
from tests.helpers import _FakeDevice, _MockVAD, _async_mock, _key_event
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder


class TestRunDaemonMultiKeyboard:
    def test_hotkey_on_any_keyboard_triggers_recording(self):
        idle_keyboard = _FakeDevice([])
        used_keyboard = _FakeDevice(
            [
                _key_event(ecodes.KEY_LEFTCTRL, 1),
                _key_event(ecodes.KEY_LEFTMETA, 1),
                _key_event(ecodes.KEY_SPACE, 1),
                _key_event(ecodes.KEY_SPACE, 0),
            ]
        )
        starts = 0
        emitted = []

        async def fake_start():
            nonlocal starts
            starts += 1
            return (
                _async_mock(),
                asyncio.create_task(asyncio.sleep(0)),
                bytearray(b"test"),
            )

        async def fake_finish(self, proc, read_task, buffer, *, vad_task=None, stop_vad=None):
            emitted.append("transcribed text")

        async def scenario():
            daemon = Daemon(None, None, TextOutput(False), None, None)
            task = asyncio.create_task(daemon.run())
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
    def test_live_mode_starts_vad_task(self):
        keyboard = _FakeDevice(
            [
                _key_event(ecodes.KEY_LEFTCTRL, 1),
                _key_event(ecodes.KEY_LEFTMETA, 1),
                _key_event(ecodes.KEY_SPACE, 1),
                _key_event(ecodes.KEY_SPACE, 0),
            ]
        )
        starts = 0

        async def fake_start():
            nonlocal starts
            starts += 1
            return ("proc", "read_task", "buffer")

        async def scenario():
            daemon = Daemon(None, None, TextOutput(False), None, _MockVAD())
            task = asyncio.create_task(daemon.run())
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
