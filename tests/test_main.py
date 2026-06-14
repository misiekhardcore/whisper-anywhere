import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from evdev import ecodes

import whisper_anywhere.daemon as daemon_module
import whisper_anywhere.keyboard as keyboard_module
import whisper_anywhere.recording as recording_module
from whisper_anywhere.audio import stop_recording, write_wav
from whisper_anywhere.lock import LOCK_PATH, _remove_lock, acquire_lock
from whisper_anywhere.output import (
    _common_prefix_len,
    emit,
    emit_final,
    emit_partial,
)
from whisper_anywhere.recording import (
    _finish_recording,
    _live_vad_loop,
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
            emit("", False)
            run.assert_not_called()

    def test_stdout_mode_writes_json(self, capsys):
        emit("hello world", True)
        out = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

    def test_ydotool_invoked(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit("hello", False)
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            emit("hello", False)
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            emit("hello", False)
            assert "ydotool not found" in capsys.readouterr().err


class TestCommonPrefixLen:
    def test_full_match(self):
        assert _common_prefix_len("hello", "hello") == 5

    def test_partial_match(self):
        assert _common_prefix_len("hello world", "hello universe") == 6

    def test_no_match(self):
        assert _common_prefix_len("abc", "xyz") == 0

    def test_empty_prev(self):
        assert _common_prefix_len("", "hello") == 0

    def test_empty_new(self):
        assert _common_prefix_len("hello", "") == 0

    def test_both_empty(self):
        assert _common_prefix_len("", "") == 0

    def test_new_is_prefix_of_prev(self):
        assert _common_prefix_len("hello world", "hello") == 5

    def test_unicode(self):
        assert _common_prefix_len("héllo", "héy") == 2


class TestEmitPartial:
    def test_noop_when_prev_equals_new(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            emit_partial("hello", "hello", False)
            run.assert_not_called()

    def test_stdout_json_shape(self, capsys):
        emit_partial("old", "new text", True)
        out = capsys.readouterr().out
        assert json.loads(out) == {"type": "partial", "text": "new text"}

    def test_ydotool_backspace_and_type(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_partial("abc", "def", False)
            calls = run.call_args_list
            # 3 backspaces = 3× (keycode:1, keycode:0)
            assert calls[0].args[0] == [
                "ydotool",
                "key",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
            ]
            assert calls[1].args[0] == ["ydotool", "type", "def"]

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            emit_partial("old", "new", False)
            assert "ydotool not found" in capsys.readouterr().err

    def test_shared_prefix_only_backspaces_suffix(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_partial("hello world", "hello universe", False)
            calls = run.call_args_list
            # "hello " is 6 common chars; backspace "world" (5 chars), type "universe"
            backspace_keys = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_append_only_backspaces_nothing(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_partial("hello", "hello world", False)
            calls = run.call_args_list
            # common prefix is all of prev_text; 0 backspaces → no key call
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_truncation_backspaces_excess_only(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_partial("hello world", "hello", False)
            calls = run.call_args_list
            # common prefix "hello" (5 chars); backspace " world" (6 chars); no type
            assert len(calls) == 1
            backspace_keys = ["14:1", "14:0"] * 6
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys


class TestEmitFinal:
    def test_stdout_json_shape(self, capsys):
        emit_final("old", "final text", True)
        out = capsys.readouterr().out
        assert json.loads(out) == {"type": "final", "text": "final text"}

    def test_no_emit_when_final_empty_stdout(self, capsys):
        emit_final("old", "", True)
        out = capsys.readouterr().out
        assert out == ""

    def test_ydotool_backspace_and_type(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_final("abc", "done", False)
            calls = run.call_args_list
            assert calls[0].args[0] == [
                "ydotool",
                "key",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
            ]
            assert calls[1].args[0] == ["ydotool", "type", "done"]

    def test_backspace_only_when_final_empty(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_final("abc", "", False)
            calls = run.call_args_list
            assert len(calls) == 1
            assert calls[0].args[0] == [
                "ydotool",
                "key",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
                "14:1",
                "14:0",
            ]

    def test_shared_prefix_final(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_final("hello world", "hello universe", False)
            calls = run.call_args_list
            backspace_keys = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_new_is_extended_final(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit_final("hello", "hello world", False)
            calls = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            emit_final("old", "final", False)
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
            return (
                _async_mock(),
                asyncio.create_task(asyncio.sleep(0)),
                bytearray(b"test"),
            )

        async def fake_finish(
            proc, read_task, buffer, model, language, stdout_mode, **kw
        ):
            emitted.append("transcribed text")

        async def scenario():
            task = asyncio.create_task(daemon_module.run_daemon(None, engine=None))
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
            patch.object(daemon_module, "_start_recording", fake_start),
            patch.object(daemon_module, "_finish_recording", fake_finish),
            patch.object(daemon_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        assert emitted == ["transcribed text"]


class TestLiveVADLoop:
    MIN_AUDIO_BYTES = int(0.25 * 16000 * 2)

    @pytest.mark.asyncio
    async def test_speech_emits_partial(self):
        buffer = bytearray(b"\x00\x01" * (8000 + 8000))
        stop_event = asyncio.Event()

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

        model = MagicMock()
        model.transcribe.return_value = "hello"

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_partial") as mock_partial,
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                _live_vad_loop(buffer, model, None, _MockVAD(), stop_event, False)
            )
            await asyncio.sleep(0.3)
            stop_event.set()
            partial, pos = await task

        mock_partial.assert_called_with("", "hello", False)
        assert partial == "hello"
        assert isinstance(pos, int)
        mock_final.assert_not_called()

    @pytest.mark.asyncio
    async def test_buffer_too_short_no_calls(self):
        buffer = bytearray(b"\x00\x01" * 1000)
        stop_event = asyncio.Event()

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

        model = MagicMock()

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_partial") as mock_partial,
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                _live_vad_loop(buffer, model, None, _MockVAD(), stop_event, False)
            )
            await asyncio.sleep(0.3)
            stop_event.set()
            partial, pos = await task

        assert partial == ""
        assert pos == 0
        mock_partial.assert_not_called()
        mock_final.assert_not_called()
        model.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_speech_no_transcription(self):
        buffer = bytearray(b"\x00\x01" * 10000)
        stop_event = asyncio.Event()

        class _MockVAD:
            def detect(self, audio, rate):
                return []

        model = MagicMock()

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_partial") as mock_partial,
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                _live_vad_loop(buffer, model, None, _MockVAD(), stop_event, False)
            )
            await asyncio.sleep(0.3)
            stop_event.set()
            partial, pos = await task

        assert partial == ""
        mock_partial.assert_not_called()
        mock_final.assert_not_called()
        model.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_silence_gap_emits_final(self):
        # Start with enough audio for min_audio check to pass.
        initial_audio = b"\x00\x01" * (8000 + 8000)
        buffer = bytearray(initial_audio)
        stop_event = asyncio.Event()
        speech_done = False

        SILENCE_THRESHOLD_BYTES = int(0.6 * 16000 * 2)  # 19200

        class _MockVAD:
            def detect(self, audio, rate):
                nonlocal speech_done
                if not speech_done and audio:
                    speech_done = True
                    return [(0, 1000)]
                return []

        async def _grow_buffer():
            # Wait for the first iteration to detect speech, then add silence.
            await asyncio.sleep(0.25)
            buffer.extend(b"\x00\x00" * (SILENCE_THRESHOLD_BYTES // 2 + 100))

        model = MagicMock()
        model.transcribe.return_value = "hello"

        grow_task = asyncio.create_task(_grow_buffer())

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_partial") as mock_partial,
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                _live_vad_loop(buffer, model, None, _MockVAD(), stop_event, False)
            )
            await asyncio.sleep(0.7)
            stop_event.set()
            partial, pos = await task

        await grow_task
        mock_partial.assert_called()
        mock_final.assert_called()
        assert partial == ""  # reset after final commit

    @pytest.mark.asyncio
    async def test_recovers_from_vad_error(self):
        buffer = bytearray(b"\x00\x01" * 20000)
        stop_event = asyncio.Event()
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

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_partial") as mock_partial,
        ):
            task = asyncio.create_task(
                _live_vad_loop(buffer, model, None, _FailingVAD(), stop_event, False)
            )
            await asyncio.sleep(0.5)
            stop_event.set()
            partial, pos = await task

        assert partial == "hello"
        mock_partial.assert_called()


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
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit"),
        ):
            await _finish_recording(proc, read_task, buffer, model, None, False)

        model.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_live_transcribes_tail_audio(self):
        """Loop covered nothing (pos=0); finish should transcribe the full buffer as tail."""
        buffer = bytearray(b"\x00\x01" * 2000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "partial text", 0

        model = MagicMock()
        model.transcribe.return_value = "tail text"

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            await _finish_recording(
                proc,
                read_task,
                buffer,
                model,
                None,
                False,
                vad_task=fake_vad_task(),
            )

        model.transcribe.assert_called_once()
        mock_final.assert_called_once_with("partial text", "tail text", False)

    @pytest.mark.asyncio
    async def test_live_no_emit_when_loop_covered_all(self):
        """Loop covered the entire buffer; no tail to transcribe."""
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "all text", len(buffer)

        model = MagicMock()

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            await _finish_recording(
                proc,
                read_task,
                buffer,
                model,
                None,
                False,
                vad_task=fake_vad_task(),
            )

        model.transcribe.assert_not_called()
        mock_final.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_emits_tail_when_partial_coverage(self):
        """Loop covered first half; finish transcribes and emits the second half."""
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))
        half = len(buffer) // 2

        async def fake_vad_task():
            return "first half", half

        model = MagicMock()
        model.transcribe.return_value = "second half"

        with (
            patch.object(recording_module, "write_wav"),
            patch.object(recording_module, "emit_final") as mock_final,
        ):
            await _finish_recording(
                proc,
                read_task,
                buffer,
                model,
                None,
                False,
                vad_task=fake_vad_task(),
            )

        model.transcribe.assert_called_once()
        mock_final.assert_called_once_with("first half", "second half", False)


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

        class _MockVAD:
            def detect(self, audio, rate):
                return [(0, 1000)]

            def reset(self):
                pass

        async def scenario():
            task = asyncio.create_task(
                daemon_module.run_daemon(None, engine=None, vad=_MockVAD())
            )
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with (
            patch.object(daemon_module, "find_keyboards", return_value=[keyboard]),
            patch.object(daemon_module, "_start_recording", fake_start),
            patch.object(daemon_module, "_finish_recording") as mock_finish,
            patch.object(daemon_module, "stop_recording", lambda proc: None),
        ):
            asyncio.run(scenario())

        assert starts == 1
        mock_finish.assert_awaited_once()
