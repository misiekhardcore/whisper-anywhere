import asyncio
import threading
from unittest.mock import patch

from evdev import ecodes

import whisper_anywhere.daemon as daemon_module
from tests.helpers import _FakeDevice, _key_event
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recording
from whisper_anywhere.state import NullStatus


class _RecorderCalls:
    def __init__(self) -> None:
        self.starts: int = 0
        self.finished: list[Recording] = []

    async def start(self) -> Recording:
        self.starts += 1
        return Recording(
            process="parec",
            reader=asyncio.create_task(asyncio.sleep(0)),
            buffer=bytearray(b"pcm"),
        )

    async def finish(self, recording: Recording) -> None:
        self.finished.append(recording)


def _combo_press_and_release() -> list:
    return [
        _key_event(ecodes.KEY_LEFTCTRL, 1),
        _key_event(ecodes.KEY_LEFTMETA, 1),
        _key_event(ecodes.KEY_SPACE, 1),
        _key_event(ecodes.KEY_LEFTCTRL, 0),
    ]


def _single_key_press_and_release(code: int) -> list:
    return [_key_event(code, 1), _key_event(code, 0)]


def _drive(events: list, hotkey_code: int | None, calls: _RecorderCalls) -> None:
    async def scenario() -> None:
        daemon: Daemon = Daemon(
            hotkey_code, lambda: None, TextOutput(False), None, NullStatus()
        )
        task: asyncio.Task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with (
        patch(
            "whisper_anywhere.keyboard.Keyboard.find_keyboards",
            return_value=[_FakeDevice(events)],
        ),
        patch("whisper_anywhere.recording.Recorder.start", calls.start),
        patch("whisper_anywhere.recording.Recorder.finish", calls.finish),
        patch.object(daemon_module, "stop_recording", lambda proc: None),
    ):
        asyncio.run(scenario())


class _GatedLoader:
    """An engine load that holds the daemon in loading until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.released = threading.Event()

    def __call__(self) -> None:
        self.entered.set()
        self.released.wait(5)
        return None


class TestStartup:
    def test_the_hotkey_is_ignored_until_the_engine_is_ready(self) -> None:
        loader: _GatedLoader = _GatedLoader()
        calls: _RecorderCalls = _RecorderCalls()

        async def scenario() -> None:
            daemon: Daemon = Daemon(
                ecodes.KEY_F12, loader, TextOutput(False), None, NullStatus()
            )
            task: asyncio.Task = asyncio.create_task(daemon.run())
            assert await asyncio.to_thread(loader.entered.wait, 5)
            await asyncio.sleep(0.1)
            assert calls.starts == 0, "the hotkey was served before the engine loaded"

            loader.released.set()
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch(
                "whisper_anywhere.keyboard.Keyboard.find_keyboards",
                return_value=[
                    _FakeDevice(_single_key_press_and_release(ecodes.KEY_F12))
                ],
            ),
            patch("whisper_anywhere.recording.Recorder.start", calls.start),
            patch("whisper_anywhere.recording.Recorder.finish", calls.finish),
            patch.object(daemon_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert calls.starts == 1
        assert len(calls.finished) == 1


class TestDictationCycle:
    def test_combo_hotkey_starts_and_finishes_once(self) -> None:
        calls: _RecorderCalls = _RecorderCalls()

        _drive(_combo_press_and_release(), None, calls)

        assert calls.starts == 1
        assert len(calls.finished) == 1

    def test_single_key_hotkey_starts_and_finishes_once(self) -> None:
        calls: _RecorderCalls = _RecorderCalls()

        _drive(_single_key_press_and_release(ecodes.KEY_F12), ecodes.KEY_F12, calls)

        assert calls.starts == 1
        assert len(calls.finished) == 1

    def test_other_single_keys_are_ignored(self) -> None:
        calls: _RecorderCalls = _RecorderCalls()

        _drive(_single_key_press_and_release(ecodes.KEY_F11), ecodes.KEY_F12, calls)

        assert calls.starts == 0
        assert calls.finished == []

    def test_release_without_press_finishes_nothing(self) -> None:
        calls: _RecorderCalls = _RecorderCalls()

        _drive(_single_key_press_and_release(ecodes.KEY_F12)[1:], ecodes.KEY_F12, calls)

        assert calls.starts == 0
        assert calls.finished == []

    def test_incomplete_combo_does_not_start(self) -> None:
        calls: _RecorderCalls = _RecorderCalls()

        _drive(
            [
                _key_event(ecodes.KEY_LEFTCTRL, 1),
                _key_event(ecodes.KEY_SPACE, 1),
                _key_event(ecodes.KEY_SPACE, 0),
            ],
            None,
            calls,
        )

        assert calls.starts == 0
        assert calls.finished == []


class TestKeyboardHotplug:
    def test_hotkey_on_any_keyboard_triggers_recording(self) -> None:
        _FakeDevice([])
        _FakeDevice(_combo_press_and_release())
        calls: _RecorderCalls = _RecorderCalls()

        _drive(_combo_press_and_release(), None, calls)

        assert calls.starts == 1
        assert len(calls.finished) == 1
