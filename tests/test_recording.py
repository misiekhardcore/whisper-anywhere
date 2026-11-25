import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from tests.helpers import _async_mock
from whisper_anywhere.audio import AUDIO, CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from whisper_anywhere.output import TextOutput
from whisper_anywhere.recording import Recorder, Recording
from whisper_anywhere.state import FAILURE_NOTE, LIMIT_NOTE, DaemonState, DaemonStatus


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


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[DaemonStatus] = []

    def publish(self, state: DaemonState, note: str | None = None) -> None:
        self.published.append(DaemonStatus(state, note))


class _StatusAwareOutput:
    def __init__(self, publisher: _FakePublisher, delivered: bool = True) -> None:
        self._publisher = publisher
        self._delivered = delivered
        self.published_at_emit: list[DaemonStatus] | None = None

    async def emit(self, text: str) -> bool:
        self.published_at_emit = list(self._publisher.published)
        return self._delivered


class TestStartRecording:
    @pytest.mark.asyncio
    async def test_capture_is_capped_at_the_configured_limit(self) -> None:
        with (
            patch(
                "whisper_anywhere.recording.asyncio.create_subprocess_exec",
                new=AsyncMock(),
            ),
            patch("whisper_anywhere.recording.read_audio", new=AsyncMock()) as read,
        ):
            recording: Recording = await Recorder.start(12)

        bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS
        assert read.call_args.kwargs["max_bytes"] == 12 * bytes_per_second
        assert read.call_args.kwargs["cap_reached"] is recording.cap_reached


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
    async def test_a_long_recording_is_decoded_in_segments_and_emitted_once(
        self,
    ) -> None:
        engine: MagicMock = MagicMock()
        engine.transcribe.side_effect = ["hello", "world"]
        recorder: Recorder = Recorder(engine, "en", TextOutput(False))

        with (
            patch(
                "whisper_anywhere.recording.split_pcm",
                return_value=[b"first", b"second"],
            ),
            patch("whisper_anywhere.recording.write_wav") as write_wav,
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        assert write_wav.call_args_list == [
            call(AUDIO, b"first"),
            call(AUDIO, b"second"),
        ]
        assert engine.transcribe.call_count == 2
        mock_emit.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_a_silent_segment_contributes_no_text(self) -> None:
        engine: MagicMock = MagicMock()
        engine.transcribe.side_effect = ["hello", "  "]
        recorder: Recorder = Recorder(engine, None, TextOutput(False))

        with (
            patch(
                "whisper_anywhere.recording.split_pcm",
                return_value=[b"first", b"second"],
            ),
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        mock_emit.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_the_limit_note_is_published_when_the_cap_ended_the_recording(
        self,
    ) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "text"
        recorder: Recorder = Recorder(engine, None, TextOutput(False), publisher)

        with (
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit", new_callable=AsyncMock),
        ):
            await recorder.finish(
                _recording(bytearray(b"\x00\x01" * 100)), note=LIMIT_NOTE
            )

        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE, LIMIT_NOTE),
        ]

    @pytest.mark.asyncio
    async def test_empty_recording_emits_nothing(self) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        recorder: Recorder = Recorder(engine, None, TextOutput(False), publisher)

        with (
            patch("whisper_anywhere.recording.write_wav") as write_wav,
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray()))

        write_wav.assert_not_called()
        engine.transcribe.assert_not_called()
        mock_emit.assert_not_called()
        assert publisher.published == [DaemonStatus(DaemonState.IDLE)]

    @pytest.mark.asyncio
    async def test_whitespace_transcript_emits_nothing_and_leaves_no_note(
        self,
    ) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "  \n\t"
        recorder: Recorder = Recorder(engine, None, TextOutput(False), publisher)

        with (
            patch("whisper_anywhere.recording.stop_recording"),
            patch("whisper_anywhere.recording.write_wav"),
            patch.object(TextOutput, "emit", new_callable=AsyncMock) as mock_emit,
        ):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        engine.transcribe.assert_called_once()
        mock_emit.assert_not_called()
        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE),
        ]

    @pytest.mark.asyncio
    async def test_processing_wraps_the_decode_and_ends_before_insertion(
        self,
    ) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "text"
        output: _StatusAwareOutput = _StatusAwareOutput(publisher)
        recorder: Recorder = Recorder(engine, None, output, publisher)

        with patch("whisper_anywhere.recording.write_wav"):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE),
        ]
        assert output.published_at_emit == publisher.published

    @pytest.mark.asyncio
    async def test_a_failed_decode_returns_to_idle_with_the_failure_note(
        self,
    ) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.side_effect = RuntimeError("model exploded")
        recorder: Recorder = Recorder(engine, None, TextOutput(False), publisher)

        with patch("whisper_anywhere.recording.write_wav"):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE, FAILURE_NOTE),
        ]

    @pytest.mark.asyncio
    async def test_a_failed_insertion_returns_to_idle_with_the_failure_note(
        self,
    ) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "text"
        output: _StatusAwareOutput = _StatusAwareOutput(publisher, delivered=False)
        recorder: Recorder = Recorder(engine, None, output, publisher)

        with patch("whisper_anywhere.recording.write_wav"):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE),
            DaemonStatus(DaemonState.IDLE, FAILURE_NOTE),
        ]

    @pytest.mark.asyncio
    async def test_a_delivered_insertion_leaves_no_note(self) -> None:
        publisher: _FakePublisher = _FakePublisher()
        engine: MagicMock = MagicMock()
        engine.transcribe.return_value = "text"
        output: _StatusAwareOutput = _StatusAwareOutput(publisher)
        recorder: Recorder = Recorder(engine, None, output, publisher)

        with patch("whisper_anywhere.recording.write_wav"):
            await recorder.finish(_recording(bytearray(b"\x00\x01" * 100)))

        assert publisher.published == [
            DaemonStatus(DaemonState.PROCESSING),
            DaemonStatus(DaemonState.IDLE),
        ]

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
