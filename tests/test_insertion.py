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
    clipboard_inserter,
    select_insertion,
)
from whisper_anywhere.insertion.clipboard import Clipboard, ClipboardContent

CHORD_COMMAND: list[str] = ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]
WTYPE_CHORD_COMMAND: list[str] = ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]
SLEEP = "whisper_anywhere.insertion.clipboard_inserter.sleep"


def _which(*available: str):
    return lambda command: f"/usr/bin/{command}" if command in available else None


class _FakeClipboard(Clipboard):
    """Stateful clipboard: one text payload, recorded calls, scripted write failure."""

    def __init__(
        self,
        initial: str | None = "",
        fail_on_write: int | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.text: str | None = initial
        self.writes: list[str] = []
        self.events: list[str] = events if events is not None else []
        self._fail_on_write = fail_on_write

    def read(self) -> ClipboardContent:
        self.events.append("read")
        return ClipboardContent(self.text)

    def write(self, text: str) -> None:
        self.writes.append(text)
        self.events.append(f"write:{text}")
        if self._fail_on_write == len(self.writes):
            raise ClipboardError("wl-copy failed (exit 1)")
        self.text = text

    def replace_externally(self, text: str | None) -> None:
        self.text = text


class _FakeChord:
    TOOL = "ydotool"

    def __init__(
        self,
        fail: bool = False,
        on_send=None,
        events: list[str] | None = None,
    ) -> None:
        self.sent: int = 0
        self.events: list[str] = events if events is not None else []
        self._fail = fail
        self._on_send = on_send

    def send(self) -> None:
        if self._fail:
            raise ChordError("ydotool key failed (exit 1)")
        self.sent += 1
        self.events.append("chord")
        if self._on_send is not None:
            self._on_send()


def _sleeps_into(events: list[str]):
    return lambda seconds: events.append("sleep")


class TestClipboardInserter:
    def test_writes_transcript_before_one_chord(self) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard(events=events)
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert events[:2] == ["read", "write:hello"]
        assert chord.sent == 1

    def test_empty_text_inserts_nothing(self) -> None:
        clipboard: _FakeClipboard = _FakeClipboard(events=[])
        chord: _FakeChord = _FakeChord(events=[])

        ClipboardInserter(clipboard, chord).insert_text("")

        assert clipboard.writes == []
        assert clipboard.events == []
        assert chord.sent == 0

    def test_restores_the_previous_clipboard_text(self) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard("copied earlier", events=events)
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert clipboard.writes == ["hello", "copied earlier"]
        assert clipboard.text == "copied earlier"

    def test_restore_waits_for_the_settle_delay(self) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard("copied earlier", events=events)
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP) as sleep:
            sleep.side_effect = _sleeps_into(events)
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert events == [
            "read",
            "write:hello",
            "chord",
            "sleep",
            "read",
            "write:copied earlier",
        ]
        assert sleep.call_args.args == (clipboard_inserter.SETTLE_DELAY_SECONDS,)

    def test_changed_clipboard_is_not_overwritten(self) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard("copied earlier", events=events)
        chord: _FakeChord = _FakeChord(
            events=events,
            on_send=lambda: clipboard.replace_externally("something else"),
        )

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert clipboard.writes == ["hello"]
        assert clipboard.text == "something else"

    def test_non_text_clipboard_is_overwritten_without_restore(self) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard(None, events=events)
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert clipboard.writes == ["hello"]
        assert clipboard.text == "hello"

    def test_failed_write_sends_no_chord_and_reports(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard(
            "copied earlier", fail_on_write=1, events=events
        )
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert chord.sent == 0
        assert clipboard.text == "copied earlier"
        err: str = capsys.readouterr().err
        assert "Clipboard insertion failed" in err
        assert "wl-copy failed" in err

    def test_failed_chord_reports_transcript_left_on_clipboard(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard("copied earlier", events=events)
        chord: _FakeChord = _FakeChord(fail=True, events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert clipboard.writes == ["hello"]
        assert clipboard.text == "hello"
        err: str = capsys.readouterr().err
        assert "Paste chord failed" in err
        assert "transcript left on the clipboard" in err

    def test_failed_restore_reports_and_keeps_the_transcript(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        events: list[str] = []
        clipboard: _FakeClipboard = _FakeClipboard(
            "copied earlier", fail_on_write=2, events=events
        )
        chord: _FakeChord = _FakeChord(events=events)

        with patch(SLEEP, _sleeps_into(events)):
            ClipboardInserter(clipboard, chord).insert_text("hello")

        assert chord.sent == 1
        assert "Clipboard restore failed" in capsys.readouterr().err


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
        assert run.call_args_list[1].args[0] == ["wl-paste", "--no-newline"]

    def test_read_non_text_is_not_text(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="image/png\n")
            content = WaylandClipboard().read()

        assert content.text is None
        assert run.call_count == 1

    def test_read_failure_is_not_text(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            content = WaylandClipboard().read()

        assert content.text is None

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
                MagicMock(returncode=0, stdout="image/png\n"),
                MagicMock(returncode=0),
                MagicMock(returncode=0),
            ]
            selection.inserter.insert_text("hello")

        commands: list[list[str]] = [call.args[0] for call in run.call_args_list]
        assert commands[-1] == WTYPE_CHORD_COMMAND

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
        assert selection.description == "typing (ydotool)"
