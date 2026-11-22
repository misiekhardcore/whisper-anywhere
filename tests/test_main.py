import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_anywhere.__main__ import main
from whisper_anywhere.config import Config
from whisper_anywhere.daemon import Daemon


class _StubEngine:
    ENGINE_ID = "sensevoice"

    def transcribe(self, path: str, language: str | None = None) -> str:
        return ""


def _start(tmp_path: Path, config_text: str) -> list[Daemon]:
    (tmp_path / "config").write_text(config_text)
    running: list[Daemon] = []

    async def fake_run(self: Daemon) -> None:
        running.append(self)

    argv: list[str] = ["whisper-anywhere", "--stdout"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(Config, "CONFIG_DIR", str(tmp_path)),
        patch.object(Config, "check_deps"),
        patch("whisper_anywhere.__main__.Lock"),
        patch("whisper_anywhere.transcribe.load_engine", return_value=_StubEngine()),
        patch.object(Daemon, "run", fake_run),
    ):
        main()
    return running


class TestStartup:
    def test_retired_vad_engine_key_still_starts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        running: list[Daemon] = _start(
            tmp_path, "hotkey=KEY_F12\nvad_engine=fsmn-vad\n"
        )

        assert len(running) == 1
        assert "live" not in capsys.readouterr().err

    def test_startup_line_reports_engine_and_hotkey(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(tmp_path, "hotkey=KEY_F12\n")

        err: str = capsys.readouterr().err
        assert "engine: sensevoice" in err
        assert "single-key" in err
