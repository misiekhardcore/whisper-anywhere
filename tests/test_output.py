import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.output import (
    KeycodeTyper,
    TextOutput,
    Typer,
    WtypeTyper,
    YdotoolTyper,
)


@pytest.fixture
def ydotoool_typer():
    with (
        patch.object(KeycodeTyper, "_init", return_value=None),
        patch.object(TextOutput, "_probe_typer", return_value=YdotoolTyper()),
    ):
        yield


@pytest.mark.usefixtures("ydotoool_typer")
class TestEmit:
    def test_empty_text_is_noop(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            TextOutput(False).emit("")
            run.assert_not_called()

    def test_stdout_mode_writes_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        TextOutput(True).emit("hello world")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

    def test_ydotool_invoked(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            TextOutput(False).emit("hello")
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
            TextOutput(False).emit_partial("hello", "hello")
            run.assert_not_called()

    def test_stdout_json_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        TextOutput(True).emit_partial("old", "new text")
        out: str = capsys.readouterr().out
        assert json.loads(out) == {"type": "partial", "text": "new text"}

    def test_ydotool_backspace_and_type(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
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
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            TextOutput(False).emit_partial("old", "new")
            assert "ydotool not found" in capsys.readouterr().err

    def test_shared_prefix_only_backspaces_suffix(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello world", "hello universe")
            calls: list[MagicMock] = run.call_args_list
            backspace_keys: list[str] = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_append_only_backspaces_nothing(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello", "hello world")
            calls: list[MagicMock] = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_truncation_backspaces_excess_only(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("hello world", "hello universe")
            calls: list[MagicMock] = run.call_args_list
            backspace_keys: list[str] = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_new_is_extended_final(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("hello", "hello world")
            calls: list[MagicMock] = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_ydotool_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            TextOutput(False).emit_final("old", "final")
            assert "ydotool not found" in capsys.readouterr().err


class TestWtypeTyper:
    def test_type_text_calls_wtype(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().type_text("zażółć")
            run.assert_called_once_with(["wtype", "zażółć"])

    def test_type_text_skips_empty(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            WtypeTyper().type_text("")
            run.assert_not_called()

    def test_backspace(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().backspace(3)
            run.assert_called_once_with(
                ["wtype", "-k", "BackSpace", "-k", "BackSpace", "-k", "BackSpace"]
            )

    def test_backspace_zero_is_noop(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            WtypeTyper().backspace(0)
            run.assert_not_called()

    def test_type_text_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            WtypeTyper().type_text("hello")
            assert "wtype failed" in capsys.readouterr().err

    def test_type_text_missing_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            WtypeTyper().type_text("hello")
            assert "wtype not found" in capsys.readouterr().err

    def test_unicode_diacritics(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            WtypeTyper().type_text("ąćęłńóśźż")
            run.assert_called_once_with(["wtype", "ąćęłńóśźż"])

    def test_check_compositor_success(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            assert WtypeTyper._check_compositor() is True

    def test_check_compositor_failure(self) -> None:
        with patch(
            "whisper_anywhere.output.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "wtype"),
        ):
            assert WtypeTyper._check_compositor() is False

    def test_check_compositor_not_found(self) -> None:
        with patch(
            "whisper_anywhere.output.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert WtypeTyper._check_compositor() is False


class TestYdotoolTyper:
    def test_type_text_calls_ydotool(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            YdotoolTyper().type_text("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_type_text_skips_empty(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            YdotoolTyper().type_text("")
            run.assert_not_called()

    def test_backspace(self) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
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
        with patch("whisper_anywhere.output.subprocess.run") as run:
            YdotoolTyper().backspace(0)
            run.assert_not_called()

    def test_type_text_failure_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            YdotoolTyper().type_text("hello")
            assert "ydotool type failed" in capsys.readouterr().err


class TestKeycodeTyper:
    def test_no_keymap_falls_back_to_ydotool(self) -> None:
        with (
            patch.object(KeycodeTyper, "_init", return_value=None),
            patch("whisper_anywhere.output.subprocess.run") as run,
        ):
            t = KeycodeTyper()
            t._keymap = None
            run.return_value = MagicMock(returncode=0)
            t.type_text("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_type_text_with_init(self) -> None:
        with (
            patch.object(KeycodeTyper, "_init", return_value=None),
            patch("whisper_anywhere.output._ydotool_key") as yk,
        ):
            t = KeycodeTyper()
            t._keymap = 1
            t._lookup = {0x61: (38, 0), 0x62: (56, 0)}

            t.type_text("ab")
            # 'a' XKB KC=38 → evdev 30, 'b' XKB KC=56 → evdev 48
            # Expect: ydotool key 30:1 30:0 48:1 48:0
            yk.assert_any_call((30, 1), (30, 0))
            yk.assert_any_call((48, 1), (48, 0))

    def test_backspace_zero_noop(self) -> None:
        t = KeycodeTyper()
        with patch.object(KeycodeTyper, "_tap_key") as tap:
            t.backspace(0)
            tap.assert_not_called()


class TestTextOutputProbe:
    def test_wtype_preferred(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/wtype"),
            patch.object(WtypeTyper, "_check_compositor", return_value=True),
        ):
            typer: Typer | None = TextOutput._probe_typer()
            assert isinstance(typer, WtypeTyper)

    def test_wtype_rejected_then_keycode(self) -> None:
        with (
            patch("shutil.which") as which,
            patch.object(KeycodeTyper, "_init", return_value=None),
        ):
            which.side_effect = lambda cmd: {
                "wtype": "/usr/bin/wtype",
                "ydotool": "/usr/bin/ydotool",
            }.get(cmd)
            kt = KeycodeTyper()
            kt._keymap = 1
            kt._socket_path = "/tmp/test.sock"
            with patch(
                "whisper_anywhere.output.KeycodeTyper", return_value=kt
            ):
                with patch.object(WtypeTyper, "_check_compositor", return_value=False):
                    typer = TextOutput._probe_typer()
                    assert isinstance(typer, KeycodeTyper)

    def test_keycode_fails_then_ydotool(self) -> None:
        with (
            patch("shutil.which") as which,
            patch.object(KeycodeTyper, "_init", return_value=None),
        ):
            which.side_effect = lambda cmd: {
                "wtype": None,
                "wl-copy": None,
                "ydotool": "/usr/bin/ydotool",
            }.get(cmd)
            kt = KeycodeTyper()
            kt._keymap = None
            with patch(
                "whisper_anywhere.output.KeycodeTyper", return_value=kt
            ):
                typer = TextOutput._probe_typer()
                assert isinstance(typer, YdotoolTyper)

    def test_no_tool_returns_none(self) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch.object(KeycodeTyper, "_init", return_value=None),
        ):
            kt = KeycodeTyper()
            kt._keymap = None
            with patch(
                "whisper_anywhere.output.KeycodeTyper", return_value=kt
            ):
                assert TextOutput._probe_typer() is None
