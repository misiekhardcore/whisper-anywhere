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

    def test_stdout_mode_writes_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        TextOutput(True).emit("hello world")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

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


class TestCommonPrefixLen:
    def test_full_match(self) -> None:
        assert TextOutput._common_prefix_len("hello", "hello") == 5

    def test_partial_match(self) -> None:
        assert TextOutput._common_prefix_len("hello world", "hello universe") == 6

    def test_no_match(self) -> None:
        assert TextOutput._common_prefix_len("abc", "xyz") == 0

    def test_empty_prev(self) -> None:
        assert TextOutput._common_prefix_len("", "hello") == 0

    def test_empty_new(self) -> None:
        assert TextOutput._common_prefix_len("hello", "") == 0

    def test_both_empty(self) -> None:
        assert TextOutput._common_prefix_len("", "") == 0

    def test_new_is_prefix_of_prev(self) -> None:
        assert TextOutput._common_prefix_len("hello world", "hello") == 5

    def test_unicode(self) -> None:
        assert TextOutput._common_prefix_len("héllo", "héy") == 2


@pytest.mark.usefixtures("ydotoool_typer")
class TestEmitPartial:
    def test_noop_when_prev_equals_new(self) -> None:
        with patch("subprocess.run") as run:
            TextOutput(False).emit_partial("hello", "hello")
            run.assert_not_called()

    def test_stdout_json_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        TextOutput(True).emit_partial("old", "new text")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"type": "partial", "text": "new text"}

    def test_ydotool_backspace_and_type(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("abc", "def")
            calls: list[MagicMock] = run.call_args_list
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

    def test_ydotool_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            TextOutput(False).emit_partial("old", "new")
            assert "ydotool not found" in capsys.readouterr().err

    def test_shared_prefix_only_backspaces_suffix(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello world", "hello universe")
            calls: list[MagicMock] = run.call_args_list
            backspace_keys: list[str] = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_append_only_backspaces_nothing(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello", "hello world")
            calls: list[MagicMock] = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_truncation_backspaces_excess_only(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello world", "hello")
            calls: list[MagicMock] = run.call_args_list
            assert len(calls) == 1
            backspace_keys: list[str] = ["14:1", "14:0"] * 6
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys


@pytest.mark.usefixtures("ydotoool_typer")
class TestEmitFinal:
    def test_stdout_json_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        TextOutput(True).emit_final("old", "final text")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"type": "final", "text": "final text"}

    def test_no_emit_when_final_empty_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        TextOutput(True).emit_final("old", "")
        out: str = capsys.readouterr().out
        assert out == ""

    def test_ydotool_backspace_and_type(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("abc", "done")
            calls: list[MagicMock] = run.call_args_list
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

    def test_backspace_only_when_final_empty(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("abc", "")
            calls: list[MagicMock] = run.call_args_list
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

    def test_shared_prefix_final(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("hello world", "hello universe")
            calls: list[MagicMock] = run.call_args_list
            backspace_keys: list[str] = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_new_is_extended_final(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("hello", "hello world")
            calls: list[MagicMock] = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_ydotool_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            TextOutput(False).emit_final("old", "final")
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

    def test_backspace(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().backspace(3)
            run.assert_called_once_with(
                ["wtype", "-k", "BackSpace", "-k", "BackSpace", "-k", "BackSpace"]
            )

    def test_backspace_zero_is_noop(self) -> None:
        with patch("subprocess.run") as run:
            WtypeTyper().backspace(0)
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

    def test_backspace(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            YdotoolTyper().backspace(3)
            run.assert_called_once_with(
                [
                    "ydotool",
                    "key",
                    "14:1",
                    "14:0",
                    "14:1",
                    "14:0",
                    "14:1",
                    "14:0",
                ]
            )

    def test_backspace_zero_is_noop(self) -> None:
        with patch("subprocess.run") as run:
            YdotoolTyper().backspace(0)
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

    def test_backspace(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            ClipboardTyper().backspace(3)
            run.assert_called_once_with(
                ["ydotool", "key", "14:1", "14:0", "14:1", "14:0", "14:1", "14:0"]
            )

    def test_backspace_zero_is_noop(self) -> None:
        with patch("subprocess.run") as run:
            ClipboardTyper().backspace(0)
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

    def test_wtype_rejected_then_clipboard(self) -> None:
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
            assert isinstance(typer, ClipboardTyper)

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
