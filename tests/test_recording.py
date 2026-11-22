import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import _async_mock
from whisper_anywhere.audio import AUDIO
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder, Recording


class _FakeProcess:
    def __init__(self) -> None:
        self.waited: int = 0

    async def wait(self) -> int:
        self.waited += 1
        return 0


def _recording(buffer: bytearray) -> Recording:
    return Recording(
        process=_async_mock(),
        reader=asyncio.create_task(asyncio.sleep(0)),
        buffer=buffer,
    )


class TestFinishRecording:
    @pytest.mark.asyncio
    async def test_one_engine_call_over_the_whole_recording(self) -> None:
        buffer: bytearray = bytearray(b"\x00\x01" * 100)
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "full text"
        recorder: Recorder = Recorder(engine, "en", TextOutput(False))

        with (
            patch("whisper_anywhere.recording.write_wav") as write_wav,
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(buffer))

        write_wav.assert_called_once_with(AUDIO, buffer)
        engine.transcribe.assert_called_once_with(AUDIO, language="en")
        mock_emit.assert_called_once_with("full text")

    @pytest.mark.asyncio
    async def test_empty_recording_emits_nothing(self) -> None:
        engine: MagicMock = MagicMock()
        recorder: Recorder = Recorder(engine, None, TextOutput(False))

        with (
            patch("whisper_anywhere.recording.write_wav") as write_wav,
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray()))

        write_wav.assert_not_called()
        engine.transcribe.assert_not_called()
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_transcript_emits_nothing(self) -> None:
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "  \n\t"
        recorder: Recorder = Recorder(engine, None, TextOutput(False))

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        engine.transcribe.assert_called_once()
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_failure_is_reported_and_not_raised(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        engine: MagicMock = MagicMock()
        engine.transcribe.side_effect = RuntimeError("model exploded")
        recorder: Recorder = Recorder(engine, None, TextOutput(False))

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        mock_emit.assert_not_called()
        assert "model exploded" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_capture_is_stopped_and_drained(self) -> None:
        process: _FakeProcess = _FakeProcess()
        recording: Recording = Recording(
            process=process,
            reader=asyncio.create_task(asyncio.sleep(0)),
            buffer=bytearray(b"\x00\x01" * 100),
        )
        recorder: Recorder = Recorder(MagicMock(), None, TextOutput(False))

        with (
            patch("whisper_anywhere.recording.stop_recording") as stop,
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit"),
        ):
            await recorder.finish(recording)

        stop.assert_called_once_with(process)
        assert process.waited == 1
