import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_anywhere.config import load_config, parse_args, CONFIG_DIR


class TestLoadConfig:
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent"
            result = load_config(str(path))
            assert result == {}

    def test_basic_key_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("key=value\nfoo=bar\n")
            result = load_config(str(path))
            assert result == {"key": "value", "foo": "bar"}

    def test_skips_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("# comment\nkey=value\n# another\n")
            result = load_config(str(path))
            assert result == {"key": "value"}

    def test_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("\n\nkey=value\n\n")
            result = load_config(str(path))
            assert result == {"key": "value"}

    def test_strips_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("  key  =  value  \n")
            result = load_config(str(path))
            assert result == {"key": "value"}

    def test_multiple_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("url=http://example.com/path\n")
            result = load_config(str(path))
            assert result == {"url": "http://example.com/path"}

    def test_empty_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("key=\n")
            result = load_config(str(path))
            assert result == {"key": ""}

    def test_no_equals_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("justaline\nkey=value\n")
            result = load_config(str(path))
            assert result == {"key": "value"}


class TestParseArgs:
    def test_defaults(self):
        with patch.object(sys, "argv", ["whisper-anywhere"]):
            args = parse_args()
            assert args.hotkey is None
            assert args.model is None

    def test_custom_hotkey(self):
        with patch.object(sys, "argv", ["whisper-anywhere", "--hotkey", "KEY_F12"]):
            args = parse_args()
            assert args.hotkey == "KEY_F12"

    def test_custom_model(self):
        with patch.object(sys, "argv", ["whisper-anywhere", "--model", "tiny.en"]):
            args = parse_args()
            assert args.model == "tiny.en"

    def test_both_args(self):
        with patch.object(sys, "argv", [
            "whisper-anywhere", "--hotkey", "KEY_GRAVE", "--model", "small",
        ]):
            args = parse_args()
            assert args.hotkey == "KEY_GRAVE"
            assert args.model == "small"


def test_config_dir_constant():
    assert CONFIG_DIR == os.path.expanduser("~/.config/whisper-anywhere")
