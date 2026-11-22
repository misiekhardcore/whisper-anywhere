import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.output import TextOutput
from whisper_anywhere.typers import (
    ClipboardTyper,
    Typer,
    WtypeTyper,
    YdotoolTyper,
)


@pytest.fixture
def ydotoool_typer():
    with patch.object(TextOutput, "_probe_typer", return_value=YdotoolTyper()):
        yield


@pytest.mark.usefixtures("ydotoool_typer")
class TestEmit:
    def test_empty_text_is_noop(self) -> None:
        with patch("subprocess.run") as run:
            TextOutput(False).emit("")
            run.assert_not_called()

    def test_none_text_is_noop(self) -> None:
        with patch("subprocess.run") as run:
            TextOutput(False).emit(None)
            run.assert_not_called()

    def test_stdout_mode_writes_final_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        TextOutput(True).emit("hello world")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"type": "final", "text": "hello world"}

    def test_stdout_mode_writes_exactly_one_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        TextOutput(True).emit("hello world")
        lines: list[str] = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1

    def test_stdout_mode_types_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("subprocess.run") as run:
            TextOutput(True).emit("hello world")
            run.assert_not_called()
        assert "ydotool" not in capsys.readouterr().err

    def test_ydotool_invoked(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            TextOutput(False).emit("hello")
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            TextOutput(False).emit("hello")
            assert "ydotool not found" in capsys.readouterr().err


class TestWtypeTyper:
    def test_type_text_calls_wtype(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().type_text("zażółć")
            run.assert_called_once_with(["wtype", "zażółć"])

    def test_type_text_skips_empty(self) -> None:
        with patch("subprocess.run") as run:
            WtypeTyper().type_text("")
            run.assert_not_called()

    def test_type_text_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            WtypeTyper().type_text("hello")
            assert "wtype failed" in capsys.readouterr().err

    def test_type_text_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            WtypeTyper().type_text("hello")
            assert "wtype not found" in capsys.readouterr().err

    def test_unicode_diacritics(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().type_text("ąćęłńóśźż")
            run.assert_called_once_with(["wtype", "ąćęłńóśźż"])

    def test_check_compositor_success(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            assert WtypeTyper._check_compositor() is True

    def test_check_compositor_failure(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "wtype"),
        ):
            assert WtypeTyper._check_compositor() is False

    def test_check_compositor_not_found(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert WtypeTyper._check_compositor() is False


class TestYdotoolTyper:
    def test_type_text_calls_ydotool(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            YdotoolTyper().type_text("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_type_text_skips_empty(self) -> None:
        with patch("subprocess.run") as run:
            YdotoolTyper().type_text("")
            run.assert_not_called()

    def test_type_text_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            YdotoolTyper().type_text("hello")
            assert "ydotool type failed" in capsys.readouterr().err


class TestClipboardTyper:
    def test_copies_and_pastes_with_save_restore(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0, stdout="old clipboard"),
                MagicMock(returncode=0),
                MagicMock(returncode=0),
                MagicMock(returncode=0),
            ]
            ClipboardTyper().type_text("hello")
            calls: list[MagicMock] = run.call_args_list
            assert calls[0].args[0] == ["wl-paste"]
            assert calls[1].args[0] == ["wl-copy", "hello"]
            assert calls[2].args[0] == [
                "ydotool",
                "key",
                "29:1",
                "47:1",
                "47:0",
                "29:0",
            ]
            assert calls[3].args[0] == ["wl-copy", "old clipboard"]

    def test_skips_empty(self) -> None:
        with patch("subprocess.run") as run:
            ClipboardTyper().type_text("")
            run.assert_not_called()

    def test_wl_paste_failure_still_types_text(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                FileNotFoundError,  # wl-paste not found
                MagicMock(returncode=0),  # wl-copy text
                MagicMock(returncode=0),  # ydotool paste
            ]
            ClipboardTyper().type_text("hello")
            calls: list[MagicMock] = run.call_args_list
            # No restore since save failed
            assert len(calls) == 3
            assert calls[1].args[0] == ["wl-copy", "hello"]

    def test_wl_copy_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                FileNotFoundError,  # wl-copy text fails → warning
                MagicMock(returncode=0),  # ydotool paste
                MagicMock(returncode=0),  # wl-copy restore (saved was "")
            ]
            ClipboardTyper().type_text("hello")
            assert "wl-copy not found" in capsys.readouterr().err


class TestTextOutputProbe:
    def test_wtype_preferred(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/wtype"),
            patch.object(WtypeTyper, "_check_compositor", return_value=True),
        ):
            typer: Typer | None = TextOutput._probe_typer()
            assert isinstance(typer, WtypeTyper)

    def test_wtype_rejected_then_ydotool(self) -> None:
        with (
            patch("shutil.which") as which,
            patch.object(WtypeTyper, "_check_compositor", return_value=False),
        ):
            which.side_effect = lambda cmd: {
                "wtype": "/usr/bin/wtype",
                "wl-copy": "/usr/bin/wl-copy",
                "ydotool": "/usr/bin/ydotool",
            }.get(cmd)

            typer: Typer | None = TextOutput._probe_typer()
            assert isinstance(typer, YdotoolTyper)

    def test_clipboard_fallback_no_wl_copy(self) -> None:
        with (
            patch("shutil.which") as which,
            patch.object(WtypeTyper, "_check_compositor", return_value=False),
        ):
            which.side_effect = lambda cmd: (
                "/usr/bin/ydotool" if cmd == "ydotool" else None
            )
            typer: Typer | None = TextOutput._probe_typer()
            assert isinstance(typer, YdotoolTyper)

    def test_no_tool_returns_none(self) -> None:
        with patch("shutil.which", return_value=None):
            assert TextOutput._probe_typer() is None
