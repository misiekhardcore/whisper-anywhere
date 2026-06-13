import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from evdev import ecodes

import whisper_anywhere.__main__ as main_module
from whisper_anywhere.__main__ import acquire_lock, _remove_lock, emit, LOCK_PATH


class TestSingleInstance:
    def setup_method(self):
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass

    def test_acquire_creates_lock_file(self):
        assert not os.path.exists(LOCK_PATH)
        acquire_lock()
        try:
            assert os.path.exists(LOCK_PATH)
        finally:
            _remove_lock()

    def test_release_frees_lock_for_reacquire(self):
        # Releasing must drop the flock so the next instance can acquire it.
        # The file is intentionally left in place (unlinking breaks flock
        # exclusion across restarts), so we assert re-acquisition, not removal.
        acquire_lock()
        _remove_lock()
        acquire_lock()
        try:
            assert os.path.exists(LOCK_PATH)
        finally:
            _remove_lock()

    def test_second_instance_denied(self):
        import fcntl

        fd1 = open(LOCK_PATH, "w")
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fd2 = open(LOCK_PATH, "w")
            with pytest.raises(OSError):
                fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd2.close()
        finally:
            fd1.close()
            os.remove(LOCK_PATH)

    def test_exits_when_locked(self):
        import fcntl

        fd = open(LOCK_PATH, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(SystemExit):
                acquire_lock()
        finally:
            fd.close()
            os.remove(LOCK_PATH)

    def test_idempotent_release(self):
        _remove_lock()
        _remove_lock()


class TestEmit:
    def test_empty_text_is_noop(self):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            emit("", False)
            run.assert_not_called()

    def test_stdout_mode_writes_json(self, capsys):
        emit("hello world", True)
        out = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

    def test_ydotool_invoked(self):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit("hello", False)
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            emit("hello", False)
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.__main__.subprocess.run", side_effect=FileNotFoundError
        ):
            emit("hello", False)
            assert "ydotool not found" in capsys.readouterr().err


def _key_event(code, value):
    event = MagicMock()
    event.type = ecodes.EV_KEY
    event.code = code
    event.value = value
    return event


class _FakeDevice:
    """Yields a scripted event sequence, then stays idle so the daemon keeps running."""

    def __init__(self, events):
        self._events = events

    async def async_read_loop(self):
        for event in self._events:
            await asyncio.sleep(0)
            yield event
        await asyncio.sleep(3600)


class TestRunDaemonMultiKeyboard:
    def test_hotkey_on_any_keyboard_triggers_recording(self):
        # Regression: with multiple keyboards connected the hotkey must work on
        # whichever one the user presses it on, not only the first device.
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
            return ("proc", "read_task", "buffer")

        async def fake_transcribe(proc, read_task, buffer, model, language=None):
            return "transcribed text"

        async def scenario():
            task = asyncio.create_task(main_module.run_daemon(None, model=None))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch.object(
                main_module,
                "find_keyboards",
                return_value=[idle_keyboard, used_keyboard],
            ),
            patch.object(main_module, "_start_recording", fake_start),
            patch.object(main_module, "transcribe", fake_transcribe),
            patch.object(main_module, "emit", lambda text, mode: emitted.append(text)),
            patch.object(main_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        assert emitted == ["transcribed text"]
