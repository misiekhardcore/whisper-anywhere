import json
import threading
from unittest.mock import MagicMock

import pytest

from whisper_anywhere.insertion import TextInserter
from whisper_anywhere.output import TextOutput


class _RecordingInserter(TextInserter):
    def __init__(self) -> None:
        self.inserted: list[str] = []
        self.thread: threading.Thread | None = None

    def insert_text(self, text: str) -> bool:
        self.inserted.append(text)
        self.thread = threading.current_thread()
        return True


class _FailingInserter(TextInserter):
    def insert_text(self, text: str) -> bool:
        return False


@pytest.mark.asyncio
class TestEmit:
    async def test_empty_text_is_noop(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        delivered: bool = await TextOutput(False, inserter).emit("")

        assert delivered is True
        assert inserter.inserted == []

    async def test_none_text_is_noop(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        delivered: bool = await TextOutput(False, inserter).emit(None)

        assert delivered is True
        assert inserter.inserted == []

    async def test_stdout_mode_writes_final_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        delivered: bool = await TextOutput(True, None).emit("hello world")

        assert delivered is True
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"type": "final", "text": "hello world"}

    async def test_stdout_mode_writes_exactly_one_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        await TextOutput(True, None).emit("hello world")

        lines: list[str] = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1

    async def test_stdout_mode_inserts_nothing(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        await TextOutput(True, inserter).emit("hello world")

        assert inserter.inserted == []

    async def test_transcript_inserted_once(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        delivered: bool = await TextOutput(False, inserter).emit("hello")

        assert delivered is True
        assert inserter.inserted == ["hello "]

    async def test_inserted_transcript_ends_with_a_space(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        await TextOutput(False, inserter).emit("hello")

        assert inserter.inserted[0].endswith(" ")

    async def test_existing_trailing_whitespace_is_kept_as_is(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        await TextOutput(False, inserter).emit("hello\n")

        assert inserter.inserted == ["hello\n"]

    async def test_insertion_runs_off_the_event_loop_thread(self) -> None:
        inserter: _RecordingInserter = _RecordingInserter()
        await TextOutput(False, inserter).emit("hello")

        assert inserter.thread is not None
        assert inserter.thread is not threading.main_thread()

    async def test_inserter_failure_does_not_raise(self) -> None:
        inserter: MagicMock = MagicMock()
        inserter.insert_text.side_effect = RuntimeError("boom")

        delivered: bool = await TextOutput(False, inserter).emit("hello")

        assert delivered is False
        inserter.insert_text.assert_called_once_with("hello ")

    async def test_refused_insertion_reports_not_delivered(self) -> None:
        delivered: bool = await TextOutput(False, _FailingInserter()).emit("hello")

        assert delivered is False
