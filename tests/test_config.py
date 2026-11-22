import os
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.config import Config
from whisper_anywhere.insertion import InsertionSelection, TextInserter


class TestLoadConfig:
    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "nonexistent"
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {}

    def test_basic_key_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("key=value\nfoo=bar\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": "value", "foo": "bar"}

    def test_skips_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("# comment\nkey=value\n# another\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": "value"}

    def test_skips_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("\n\nkey=value\n\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": "value"}

    def test_strips_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("  key  =  value  \n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": "value"}

    def test_multiple_equals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("url=http://example.com/path\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"url": "http://example.com/path"}

    def test_empty_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("key=\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": ""}

    def test_no_equals_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("justaline\nkey=value\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result == {"key": "value"}

    def test_retired_vad_engine_key_is_parsed_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path: Path = Path(tmp) / "config"
            path.write_text("hotkey=KEY_F12\nvad_engine=fsmn-vad\n")
            result: dict[str, str] = Config.load_config(str(path))
            assert result["hotkey"] == "KEY_F12"


class TestParseArgs:
    def test_defaults(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere"]):
            args: Namespace = Config.parse_args()
            assert args.hotkey is None
            assert args.model is None

    def test_custom_hotkey(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--hotkey", "KEY_F12"]):
            args: Namespace = Config.parse_args()
            assert args.hotkey == "KEY_F12"

    def test_custom_model(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--model", "tiny.en"]):
            args: Namespace = Config.parse_args()
            assert args.model == "tiny.en"

    def test_both_args(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "whisper-anywhere",
                "--hotkey",
                "KEY_GRAVE",
                "--model",
                "small",
            ],
        ):
            args: Namespace = Config.parse_args()
            assert args.hotkey == "KEY_GRAVE"
            assert args.model == "small"

    def test_stdout_flag(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--stdout"]):
            args: Namespace = Config.parse_args()
            assert args.stdout is True

    def test_language_default_none(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere"]):
            assert Config.parse_args().language is None

    def test_custom_language(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--language", "pl"]):
            assert Config.parse_args().language == "pl"

    def test_engine_default_none(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere"]):
            assert Config.parse_args().engine is None

    def test_custom_engine(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--engine", "sensevoice"]):
            assert Config.parse_args().engine == "sensevoice"

    def test_retired_vad_flag_is_rejected(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad"]):
            with pytest.raises(SystemExit) as exc:
                Config.parse_args()
            assert exc.value.code == 2


class TestVersion:
    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--version"]):
            with pytest.raises(SystemExit) as exc:
                Config.parse_args()
            assert exc.value.code == 0
            out: str = capsys.readouterr().out
            assert "whisper-anywhere" in out

    def test_version_contains_number(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--version"]):
            with pytest.raises(SystemExit):
                Config.parse_args()
            out: str = capsys.readouterr().out
            assert any(c.isdigit() for c in out)


class TestGetVersion:
    def test_success(self) -> None:
        with patch("importlib.metadata.version", return_value="1.0.0"):
            assert Config._get_version() == "1.0.0"

    def test_fallback_on_exception(self) -> None:
        with patch("importlib.metadata.version", side_effect=Exception("no package")):
            assert Config._get_version() == "unknown"


class _FakeInserter(TextInserter):
    def insert_text(self, text: str) -> None: ...


class TestCheckDepsInsertion:
    @staticmethod
    def _present_dependencies():
        return patch(
            "whisper_anywhere.config.subprocess.run",
            return_value=MagicMock(returncode=0),
        )

    def test_missing_inserter_exits_naming_package(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        selection: InsertionSelection = InsertionSelection(
            None, "no insertion tool: install ydotool (sudo apt install ydotool)", None
        )
        with (
            self._present_dependencies(),
            patch.dict(sys.modules, {"vosk": MagicMock()}),
            pytest.raises(SystemExit) as exc,
        ):
            Config.check_deps("vosk", selection)

        assert exc.value.code == 1
        assert "sudo apt install ydotool" in capsys.readouterr().err

    def test_clipboard_warning_is_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        selection: InsertionSelection = InsertionSelection(
            _FakeInserter(),
            "typing (ydotool)",
            "Clipboard insertion unavailable: install it: sudo apt install wl-clipboard",
        )
        with (
            self._present_dependencies(),
            patch.dict(sys.modules, {"vosk": MagicMock()}),
        ):
            Config.check_deps("vosk", selection)

        assert "sudo apt install wl-clipboard" in capsys.readouterr().err

    def test_stdout_mode_skips_insertion_check(self) -> None:
        with (
            self._present_dependencies(),
            patch.dict(sys.modules, {"vosk": MagicMock()}),
        ):
            Config.check_deps("vosk")


def test_config_dir_constant() -> None:
    assert Config.CONFIG_DIR == os.path.expanduser("~/.config/whisper-anywhere")
