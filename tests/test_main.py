import asyncio
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from evdev import ecodes

import whisper_anywhere.__main__ as main_module
from whisper_anywhere.__main__ import (
    acquire_lock,
    _remove_lock,
    emit,
    LOCK_PATH,
    _live_vad_loop,
    _finish_recording,
    _start_recording,
)


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
            return (_async_mock(), asyncio.create_task(asyncio.sleep(0)), bytearray(b"test"))

        async def fake_finish(proc, read_task, buffer, model, language, stdout_mode, **kw):
            emitted.append("transcribed text")

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
            patch.object(main_module, "_finish_recording", fake_finish),
            patch.object(main_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        assert emitted == ["transcribed text"]


class TestLiveVADLoop:
    MIN_AUDIO_BYTES = int(0.25 * 16000 * 2)

    @pytest.mark.asyncio
    async def test_transcribes_when_speech_detected(self):
        buffer = bytearray(b"\x00\x01" * (8000 + 8000))
        stop_event = asyncio.Event()
        emitted = []

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

        model = MagicMock()
        model.transcribe.return_value = "hello"

        task = asyncio.create_task(
            _live_vad_loop(
                buffer, model, None, lambda t, m: emitted.append(t),
                _MockVAD(), stop_event, False,
            )
        )
        await asyncio.sleep(0.3)
        stop_event.set()
        result = await task

        assert result == "hello"
        assert emitted == ["hello"]

    @pytest.mark.asyncio
    async def test_skips_when_buffer_too_short(self):
        buffer = bytearray(b"\x00\x01" * 1000)
        stop_event = asyncio.Event()
        emitted = []

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

        model = MagicMock()

        task = asyncio.create_task(
            _live_vad_loop(
                buffer, model, None, lambda t, m: emitted.append(t),
                _MockVAD(), stop_event, False,
            )
        )
        await asyncio.sleep(0.3)
        stop_event.set()
        result = await task

        assert result == ""
        assert emitted == []
        model.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_speech_no_transcription(self):
        buffer = bytearray(b"\x00\x01" * 10000)
        stop_event = asyncio.Event()
        emitted = []

        class _MockVAD:
            def detect(self, audio, rate):
                return []

        model = MagicMock()

        task = asyncio.create_task(
            _live_vad_loop(
                buffer, model, None, lambda t, m: emitted.append(t),
                _MockVAD(), stop_event, False,
            )
        )
        await asyncio.sleep(0.3)
        stop_event.set()
        result = await task

        assert result == ""
        assert emitted == []
        model.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_only_new_suffix_emitted(self):
        buffer = bytearray(b"\x00\x01" * 20000)
        stop_event = asyncio.Event()
        emitted = []
        call_count = 0

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

        model = MagicMock()
        def _transcribe(t, language):
            nonlocal call_count
            call_count += 1
            return "hello" if call_count == 1 else "hello world"
        model.transcribe = _transcribe

        task = asyncio.create_task(
            _live_vad_loop(
                buffer, model, None, lambda t, m: emitted.append(t),
                _MockVAD(), stop_event, False,
            )
        )
        await asyncio.sleep(0.5)
        stop_event.set()
        result = await task

        assert result == "hello world"
        assert emitted == ["hello", " world"]

    @pytest.mark.asyncio
    async def test_recovers_from_vad_error(self):
        buffer = bytearray(b"\x00\x01" * 20000)
        stop_event = asyncio.Event()
        emitted = []
        call_count = 0

        class _FailingVAD:
            def detect(self, audio, rate):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("vad failure")
                return [(0, 1000)]

        model = MagicMock()
        model.transcribe.return_value = "hello"

        task = asyncio.create_task(
            _live_vad_loop(
                buffer, model, None, lambda t, m: emitted.append(t),
                _FailingVAD(), stop_event, False,
            )
        )
        await asyncio.sleep(0.5)
        stop_event.set()
        result = await task

        assert result == "hello"
        assert emitted == ["hello"]


def _async_mock():
    m = MagicMock()
    async def async_wait():
        return 0
    m.wait = async_wait
    return m


class TestFinishRecording:
    @pytest.mark.asyncio
    async def test_non_live_transcribes_full_buffer(self):
        buffer = bytearray(b"\x00\x01" * 100)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))
        model = MagicMock()
        model.transcribe.return_value = "full text"

        with (
            patch.object(main_module, "write_wav"),
            patch.object(main_module, "emit") as mock_emit,
        ):
            await _finish_recording(proc, read_task, buffer, model, None, False)

        model.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_live_transcribes_full_buffer(self):
        buffer = bytearray(b"\x00\x01" * 2000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "partial text"

        model = MagicMock()
        model.transcribe.return_value = "partial text"

        with (
            patch.object(main_module, "write_wav"),
            patch.object(main_module, "emit") as mock_emit,
        ):
            await _finish_recording(
                proc, read_task, buffer, model, None, False,
                vad_task=fake_vad_task(), live_mode=True,
            )

        model.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_live_emits_only_new_suffix(self):
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "already typed"

        model = MagicMock()
        model.transcribe.return_value = "already typed more text"

        with (
            patch.object(main_module, "write_wav"),
            patch.object(main_module, "emit") as mock_emit,
        ):
            await _finish_recording(
                proc, read_task, buffer, model, None, False,
                vad_task=fake_vad_task(), live_mode=True,
            )

        model.transcribe.assert_called_once()
        mock_emit.assert_called_once_with(" more text", False)

    @pytest.mark.asyncio
    async def test_live_no_suffix_when_identical(self):
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "final text"

        model = MagicMock()
        model.transcribe.return_value = "final text"

        with (
            patch.object(main_module, "write_wav"),
            patch.object(main_module, "emit") as mock_emit,
        ):
            await _finish_recording(
                proc, read_task, buffer, model, None, False,
                vad_task=fake_vad_task(), live_mode=True,
            )

        model.transcribe.assert_called_once()
        mock_emit.assert_not_called()


class TestRunDaemonLiveMode:
    def test_live_mode_starts_vad_task(self):
        keyboard = _FakeDevice([
            _key_event(ecodes.KEY_LEFTCTRL, 1),
            _key_event(ecodes.KEY_LEFTMETA, 1),
            _key_event(ecodes.KEY_SPACE, 1),
            _key_event(ecodes.KEY_SPACE, 0),
        ])
        starts = 0
        emitted = []

        async def fake_start():
            nonlocal starts
            starts += 1
            return ("proc", "read_task", "buffer")

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]
            def reset(self):
                pass

        async def scenario():
            task = asyncio.create_task(
                main_module.run_daemon(
                    None, model=None, live_mode=True, vad=_MockVAD()
                )
            )
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch.object(main_module, "find_keyboards", return_value=[keyboard]),
            patch.object(main_module, "_start_recording", fake_start),
            patch.object(main_module, "_finish_recording") as mock_finish,
            patch.object(main_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        mock_finish.assert_awaited_once()
