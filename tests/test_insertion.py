import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.insertion import (
    ChordError,
    ClipboardError,
    ClipboardInserter,
    TypingInserter,
    WaylandClipboard,
    WtypeChord,
    YdotoolChord,
    select_insertion,
)

CHORD_COMMAND: list[str] = ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]
WTYPE_CHORD_COMMAND: list[str] = ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]


def _which(*available: str):
    return lambda command: f"/usr/bin/{command}" if command in available else None


class _RecordingClipboard:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail

    def read(self):
        return MagicMock()

    def write(self, text: str) -> None:
        if self._fail:
            raise ClipboardError("wl-copy failed (exit 1)")
        self.calls.append(("write", text))


class _RecordingChord:
    TOOL = "ydotool"

    def __init__(self, fail: bool = False) -> None:
        self.sent: int = 0
        self._fail = fail

    def send(self) -> None:
        if self._fail:
            raise ChordError("ydotool key failed (exit 1)")
        self.sent += 1


class TestClipboardInserter:
    def test_writes_transcript_before_one_chord(self) -> None:
        order: list[str] = []
        clipboard: MagicMock = MagicMock()
        clipboard.write.side_effect = lambda text: order.append(f"write:{text}")
        chord: MagicMock = MagicMock()
        chord.send.side_effect = lambda: order.append("chord")

        ClipboardInserter(clipboard, chord).insert_text("hello")

        assert order == ["write:hello", "chord"]

    def test_empty_text_inserts_nothing(self) -> None:
        clipboard: _RecordingClipboard = _RecordingClipboard()
        chord: _RecordingChord = _RecordingChord()

        ClipboardInserter(clipboard, chord).insert_text("")

        assert clipboard.calls == []
        assert chord.sent == 0

    def test_failed_write_sends_no_chord_and_reports(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        clipboard: _RecordingClipboard = _RecordingClipboard(fail=True)
        chord: _RecordingChord = _RecordingChord()

        ClipboardInserter(clipboard, chord).insert_text("hello")

        assert chord.sent == 0
        err: str = capsys.readouterr().err
        assert "Clipboard insertion failed" in err
        assert "wl-copy failed" in err

    def test_failed_chord_reports_transcript_left_on_clipboard(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        clipboard: _RecordingClipboard = _RecordingClipboard()
        chord: _RecordingChord = _RecordingChord(fail=True)

        ClipboardInserter(clipboard, chord).insert_text("hello")

        assert clipboard.calls == [("write", "hello")]
        err: str = capsys.readouterr().err
        assert "Paste chord failed" in err
        assert "transcript left on the clipboard" in err


class TestWaylandClipboard:
    def test_write_pipes_text_to_wl_copy(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WaylandClipboard().write("hello")

        call = run.call_args
        assert call.args[0] == ["wl-copy"]
        assert call.kwargs["input"] == "hello"

    def test_write_does_not_inherit_standard_streams(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WaylandClipboard().write("hello")

        kwargs = run.call_args.kwargs
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL

    def test_forked_selection_owner_cannot_hang_the_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_wl_copy: Path = tmp_path / "wl-copy"
        fake_wl_copy.write_text(
            "#!/usr/bin/env bash\ncat >/dev/null\nsleep 3 &\nexit 0\n"
        )
        fake_wl_copy.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

        started: float = time.monotonic()
        WaylandClipboard().write("hello")
        elapsed: float = time.monotonic() - started

        assert elapsed < 1.5, "insertion waited for the forked selection owner"

    def test_write_missing_tool_names_package(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(ClipboardError) as exc:
                WaylandClipboard().write("hello")

        assert "sudo apt install wl-clipboard" in str(exc.value)

    def test_write_failure_raises(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            with pytest.raises(ClipboardError):
                WaylandClipboard().write("hello")

    def test_read_returns_text(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0, stdout="text/plain\ntext/html\n"),
                MagicMock(returncode=0, stdout="hello"),
            ]
            content = WaylandClipboard().read()

        assert content.text == "hello"
        assert content.is_text is True
        assert run.call_args_list[1].args[0] == ["wl-paste", "--no-newline"]

    def test_read_non_text_is_not_text(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="image/png\n")
            content = WaylandClipboard().read()

        assert content.text is None
        assert content.is_text is False
        assert run.call_count == 1

    def test_read_failure_is_not_text(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            content = WaylandClipboard().read()

        assert content.is_text is False

    def test_read_does_not_inherit_standard_streams(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="")
            WaylandClipboard().read()

        for call in run.call_args_list:
            assert call.kwargs["stdin"] is subprocess.DEVNULL
            assert call.kwargs["stderr"] is subprocess.DEVNULL


class TestChords:
    def test_ydotool_sends_one_ctrl_v(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            YdotoolChord().send()

        call = run.call_args
        assert call.args[0] == CHORD_COMMAND
        assert call.kwargs["stdout"] is subprocess.DEVNULL
        assert call.kwargs["stderr"] is subprocess.DEVNULL

    def test_wtype_sends_one_ctrl_v(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeChord().send()

        assert run.call_args.args[0] == WTYPE_CHORD_COMMAND

    def test_ydotool_missing_names_package(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(ChordError) as exc:
                YdotoolChord().send()

        assert "sudo apt install ydotool" in str(exc.value)

    def test_ydotool_failure_points_at_service(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            with pytest.raises(ChordError) as exc:
                YdotoolChord().send()

        assert "ydotool.service" in str(exc.value)

    def test_wtype_failure_raises(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            with pytest.raises(ChordError):
                WtypeChord().send()


class TestTypingInserter:
    def test_ydotool_types_the_transcript(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TypingInserter("ydotool").insert_text("hello")

        call = run.call_args
        assert call.args[0] == ["ydotool", "type", "hello"]
        assert call.kwargs["stdout"] is subprocess.DEVNULL
        assert call.kwargs["stderr"] is subprocess.DEVNULL

    def test_wtype_types_the_transcript(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TypingInserter("wtype").insert_text("zażółć")

        assert run.call_args.args[0] == ["wtype", "zażółć"]

    def test_empty_text_types_nothing(self) -> None:
        with patch("subprocess.run") as run:
            TypingInserter("ydotool").insert_text("")

        run.assert_not_called()

    def test_ydotool_failure_reports(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            TypingInserter("ydotool").insert_text("hello")

        assert "ydotool type failed" in capsys.readouterr().err

    def test_missing_tool_reports_package(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            TypingInserter("wtype").insert_text("hello")

        err: str = capsys.readouterr().err
        assert "wtype not found" in err
        assert "sudo apt install wtype" in err


class TestSelectInsertion:
    def test_wayland_with_all_tools_prefers_clipboard(self) -> None:
        selection = select_insertion(
            which=_which("wl-copy", "wl-paste", "ydotool"),
            session_type="wayland",
        )

        assert isinstance(selection.inserter, ClipboardInserter)
        assert selection.warning is None
        assert "clipboard paste" in selection.description

    def test_missing_clipboard_falls_back_to_typing_and_explains(self) -> None:
        selection = select_insertion(which=_which("ydotool"), session_type="wayland")

        assert isinstance(selection.inserter, TypingInserter)
        assert selection.warning is not None
        assert "sudo apt install wl-clipboard" in selection.warning

    def test_clipboard_chord_uses_wtype_when_ydotool_absent(self) -> None:
        selection = select_insertion(
            which=_which("wl-copy", "wl-paste", "wtype"),
            session_type="wayland",
        )

        assert isinstance(selection.inserter, ClipboardInserter)
        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=0),
            ]
            selection.inserter.insert_text("hello")

        assert run.call_args_list[1].args[0] == WTYPE_CHORD_COMMAND

    def test_no_chord_injector_reports_ydotool(self) -> None:
        selection = select_insertion(
            which=_which("wl-copy", "wl-paste"), session_type="wayland"
        )

        assert selection.inserter is None
        assert "sudo apt install ydotool" in selection.description

    def test_x11_session_uses_typing(self) -> None:
        selection = select_insertion(
            which=_which("wl-copy", "wl-paste", "ydotool"),
            session_type="x11",
        )

        assert isinstance(selection.inserter, TypingInserter)
        assert selection.warning is not None
        assert "Wayland session" in selection.warning

    def test_unknown_session_uses_typing(self) -> None:
        selection = select_insertion(which=_which("ydotool"), session_type="")

        assert isinstance(selection.inserter, TypingInserter)


class TestDescription:
    def test_typing_description_names_tool(self) -> None:
        selection = select_insertion(which=_which("ydotool"), session_type="x11")

        assert selection.description == "typing (ydotool)"
