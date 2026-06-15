import os
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_anywhere.config import Config


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

    def test_vad_default_none(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere"]):
            assert Config.parse_args().vad is None

    def test_vad_without_value_uses_const(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad"]):
            assert Config.parse_args().vad == "fsmn-vad"

    def test_vad_explicit_engine(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad", "fsmn-vad"]):
            assert Config.parse_args().vad == "fsmn-vad"

    def test_vad_off(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad=off"]):
            assert Config.parse_args().vad == "off"

    def test_vad_false(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad=false"]):
            assert Config.parse_args().vad == "false"

    def test_vad_zero(self) -> None:
        with patch.object(sys, "argv", ["whisper-anywhere", "--vad=0"]):
            assert Config.parse_args().vad == "0"


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


def test_config_dir_constant() -> None:
    assert Config.CONFIG_DIR == os.path.expanduser("~/.config/whisper-anywhere")
