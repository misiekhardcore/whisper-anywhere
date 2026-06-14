import json
from unittest.mock import MagicMock, patch

from whisper_anywhere.output import TextOutput


class TestEmit:
    def test_empty_text_is_noop(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            TextOutput(False).emit("")
            run.assert_not_called()

    def test_stdout_mode_writes_json(self, capsys):
        TextOutput(True).emit("hello world")
        out = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

    def test_ydotool_invoked(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit("hello")
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            TextOutput(False).emit("hello")
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            TextOutput(False).emit("hello")
            assert "ydotool not found" in capsys.readouterr().err


class TestCommonPrefixLen:
    def test_full_match(self):
        assert TextOutput._common_prefix_len("hello", "hello") == 5

    def test_partial_match(self):
        assert TextOutput._common_prefix_len("hello world", "hello universe") == 6

    def test_no_match(self):
        assert TextOutput._common_prefix_len("abc", "xyz") == 0

    def test_empty_prev(self):
        assert TextOutput._common_prefix_len("", "hello") == 0

    def test_empty_new(self):
        assert TextOutput._common_prefix_len("hello", "") == 0

    def test_both_empty(self):
        assert TextOutput._common_prefix_len("", "") == 0

    def test_new_is_prefix_of_prev(self):
        assert TextOutput._common_prefix_len("hello world", "hello") == 5

    def test_unicode(self):
        assert TextOutput._common_prefix_len("héllo", "héy") == 2


class TestEmitPartial:
    def test_noop_when_prev_equals_new(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            TextOutput(False).emit_partial("hello", "hello")
            run.assert_not_called()

    def test_stdout_json_shape(self, capsys):
        TextOutput(True).emit_partial("old", "new text")
        out = capsys.readouterr().out
        assert json.loads(out) == {"type": "partial", "text": "new text"}

    def test_ydotool_backspace_and_type(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("abc", "def")
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
            assert calls[1].args[0] == ["ydotool", "type", "def"]

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            TextOutput(False).emit_partial("old", "new")
            assert "ydotool not found" in capsys.readouterr().err

    def test_shared_prefix_only_backspaces_suffix(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello world", "hello universe")
            calls = run.call_args_list
            backspace_keys = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_append_only_backspaces_nothing(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello", "hello world")
            calls = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_truncation_backspaces_excess_only(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_partial("hello world", "hello")
            calls = run.call_args_list
            assert len(calls) == 1
            backspace_keys = ["14:1", "14:0"] * 6
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys


class TestEmitFinal:
    def test_stdout_json_shape(self, capsys):
        TextOutput(True).emit_final("old", "final text")
        out = capsys.readouterr().out
        assert json.loads(out) == {"type": "final", "text": "final text"}

    def test_no_emit_when_final_empty_stdout(self, capsys):
        TextOutput(True).emit_final("old", "")
        out = capsys.readouterr().out
        assert out == ""

    def test_ydotool_backspace_and_type(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("abc", "done")
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
            TextOutput(False).emit_final("abc", "")
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
            TextOutput(False).emit_final("hello world", "hello universe")
            calls = run.call_args_list
            backspace_keys = ["14:1", "14:0"] * 5
            assert calls[0][0][0] == ["ydotool", "key"] + backspace_keys
            assert calls[1][0][0] == ["ydotool", "type", "universe"]

    def test_new_is_extended_final(self):
        with patch("whisper_anywhere.output.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            TextOutput(False).emit_final("hello", "hello world")
            calls = run.call_args_list
            assert len(calls) == 1
            assert calls[0][0][0] == ["ydotool", "type", " world"]

    def test_ydotool_missing_warns(self, capsys):
        with patch(
            "whisper_anywhere.output.subprocess.run", side_effect=FileNotFoundError
        ):
            TextOutput(False).emit_final("old", "final")
            assert "ydotool not found" in capsys.readouterr().err
