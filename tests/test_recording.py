import asyncio
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers import _MockVAD, _async_mock
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder


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
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_partial") as mock_partial,
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                recorder.live_vad_loop(buffer, stop_event)
            )
            await asyncio.sleep(0.3)
            stop_event.set()
            partial, pos = await task

        mock_partial.assert_called_with("", "hello")
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
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_partial") as mock_partial,
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                recorder.live_vad_loop(buffer, stop_event)
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
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_partial") as mock_partial,
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                recorder.live_vad_loop(buffer, stop_event)
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
        initial_audio = b"\x00\x01" * (8000 + 8000)
        buffer = bytearray(initial_audio)
        stop_event = asyncio.Event()
        speech_done = False

        SILENCE_THRESHOLD_BYTES = int(0.6 * 16000 * 2)

        class _MockVAD:
            def detect(self, audio, rate):
                nonlocal speech_done
                if not speech_done and audio:
                    speech_done = True
                    return [(0, 1000)]
                return []

        async def _grow_buffer():
            await asyncio.sleep(0.25)
            buffer.extend(b"\x00\x00" * (SILENCE_THRESHOLD_BYTES // 2 + 100))

        model = MagicMock()
        model.transcribe.return_value = "hello"
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        grow_task = asyncio.create_task(_grow_buffer())

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_partial") as mock_partial,
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            task = asyncio.create_task(
                recorder.live_vad_loop(buffer, stop_event)
            )
            await asyncio.sleep(0.7)
            stop_event.set()
            partial, pos = await task

        await grow_task
        mock_partial.assert_called()
        mock_final.assert_called()
        assert partial == ""

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
        output = TextOutput(False)
        recorder = Recorder(model, None, _FailingVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_partial") as mock_partial,
        ):
            task = asyncio.create_task(
                recorder.live_vad_loop(buffer, stop_event)
            )
            await asyncio.sleep(0.5)
            stop_event.set()
            partial, pos = await task

        assert partial == "hello"
        mock_partial.assert_called()


class TestFinishRecording:
    @pytest.mark.asyncio
    async def test_non_live_transcribes_full_buffer(self):
        buffer = bytearray(b"\x00\x01" * 100)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))
        model = MagicMock()
        model.transcribe.return_value = "full text"
        output = TextOutput(False)
        recorder = Recorder(model, None, None, output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit") as mock_emit,
        ):
            await recorder.finish(proc, read_task, buffer)

        model.transcribe.assert_called_once()
        mock_emit.assert_called_once_with("full text")

    @pytest.mark.asyncio
    async def test_live_transcribes_tail_audio(self):
        buffer = bytearray(b"\x00\x01" * 2000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "partial text", 0

        model = MagicMock()
        model.transcribe.return_value = "tail text"
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            await recorder.finish(
                proc, read_task, buffer, vad_task=fake_vad_task()
            )

        model.transcribe.assert_called_once()
        mock_final.assert_called_once_with("partial text", "tail text")

    @pytest.mark.asyncio
    async def test_live_no_emit_when_loop_covered_all(self):
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))

        async def fake_vad_task():
            return "all text", len(buffer)

        model = MagicMock()
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            await recorder.finish(
                proc, read_task, buffer, vad_task=fake_vad_task()
            )

        model.transcribe.assert_not_called()
        mock_final.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_emits_tail_when_partial_coverage(self):
        buffer = bytearray(b"\x00\x01" * 3000)
        proc = _async_mock()
        read_task = asyncio.create_task(asyncio.sleep(0))
        half = len(buffer) // 2

        async def fake_vad_task():
            return "first half", half

        model = MagicMock()
        model.transcribe.return_value = "second half"
        output = TextOutput(False)
        recorder = Recorder(model, None, _MockVAD(), output)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit_final") as mock_final,
        ):
            await recorder.finish(
                proc, read_task, buffer, vad_task=fake_vad_task()
            )

        model.transcribe.assert_called_once()
        mock_final.assert_called_once_with("first half", "second half")
