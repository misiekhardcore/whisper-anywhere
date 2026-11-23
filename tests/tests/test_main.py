import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_anywhere.__main__ import main
from whisper_anywhere.config import Config
from whisper_anywhere.daemon import Daemon
from whisper_anywhere.insertion import InsertionSelection, TextInserter
from whisper_anywhere.state import DaemonState, DaemonStatus, StatusServer
from whisper_anywhere.tray.client import StatusClient, send_quit

TIMEOUT = 5


class _StubEngine:
    ENGINE_ID = "sensevoice"

    def transcribe(self, path: str, language: str | None = None) -> str:
        return ""


class _FakeInserter(TextInserter):
    def insert_text(self, text: str) -> None: ...


def _wait_for_socket(socket_path: Path, timeout: float = TIMEOUT) -> None:
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"the daemon never bound {socket_path}")


def _read_status_now(socket_path: Path) -> DaemonStatus | None:
    """The status the daemon publishes right now, or None without a socket."""
    try:
        with StatusClient(str(socket_path)) as client:
            client.connect()
            return client.read_status()
    except OSError:
        return None


def _start(
    tmp_path: Path,
    config_text: str,
    argv: list[str] | None = None,
    selection: InsertionSelection | None = None,
) -> list[Daemon]:
    (tmp_path / "config").write_text(config_text)
    running: list[Daemon] = []

    async def fake_run(self: Daemon) -> None:
        running.append(self)

    resolved: InsertionSelection = selection or InsertionSelection(None, "stdout", None)
    with (
        patch.object(sys, "argv", argv or ["whisper-anywhere", "--stdout"]),
        patch.object(Config, "CONFIG_DIR", str(tmp_path)),
        patch.object(Config, "check_deps"),
        patch("whisper_anywhere.__main__.select_insertion", return_value=resolved),
        patch("whisper_anywhere.__main__.Lock"),
        patch("whisper_anywhere.transcribe.load_engine", return_value=_StubEngine()),
        patch.object(Daemon, "run", fake_run),
    ):
        main()
    return running


class TestStartup:
    def test_the_status_socket_reports_loading_before_the_engine_loads(
        self, tmp_path: Path
    ) -> None:
        """A slow model download must be observable, not a silent dead hotkey."""
        socket_path: Path = tmp_path / "state.sock"
        observed: list[DaemonStatus | None] = []
        loaded: threading.Event = threading.Event()

        def record_status(
            _engine_id: str, _model_id: str | None, _language: str | None
        ) -> _StubEngine:
            observed.append(_read_status_now(socket_path))
            loaded.set()
            return _StubEngine()

        def run_main() -> None:
            with (
                patch.object(sys, "argv", ["whisper-anywhere", "--stdout"]),
                patch.object(Config, "CONFIG_DIR", str(tmp_path)),
                patch.object(Config, "check_deps"),
                patch("whisper_anywhere.__main__.Lock"),
                patch("whisper_anywhere.__main__.signal.signal"),
                patch("whisper_anywhere.transcribe.load_engine", record_status),
                patch(
                    "whisper_anywhere.daemon.StatusServer",
                    lambda: StatusServer(str(socket_path)),
                ),
                patch(
                    "whisper_anywhere.keyboard.Keyboard.find_keyboards",
                    return_value=[],
                ),
            ):
                main()

        worker: threading.Thread = threading.Thread(target=run_main, daemon=True)
        worker.start()
        try:
            assert loaded.wait(TIMEOUT), "the engine loader was never called"
            _wait_for_socket(socket_path)
            send_quit(str(socket_path))
        finally:
            worker.join(TIMEOUT)

        assert not worker.is_alive(), "the daemon did not stop after quit"
        assert observed == [DaemonStatus(DaemonState.LOADING)]

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

    def test_startup_line_reports_stdout_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(tmp_path, "hotkey=KEY_F12\n")

        assert "insertion: stdout" in capsys.readouterr().err

    def test_startup_line_reports_clipboard_insertion(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(
            tmp_path,
            "hotkey=KEY_F12\n",
            argv=["whisper-anywhere"],
            selection=InsertionSelection(
                _FakeInserter(), "clipboard paste (ydotool + wl-clipboard)", None
            ),
        )

        assert "insertion: clipboard paste" in capsys.readouterr().err

    def test_insertion_strategy_is_resolved_once_and_consumed(
        self, tmp_path: Path
    ) -> None:
        inserter: _FakeInserter = _FakeInserter()
        selection: InsertionSelection = InsertionSelection(
            inserter,
            "typing (ydotool)",
            "Clipboard insertion unavailable: install wl-clipboard",
        )

        async def fake_run(self: Daemon) -> None:
            return None

        with (
            patch.object(sys, "argv", ["whisper-anywhere"]),
            patch.object(Config, "CONFIG_DIR", str(tmp_path)),
            patch.object(Config, "check_deps") as check_deps,
            patch(
                "whisper_anywhere.__main__.select_insertion",
                return_value=selection,
            ) as select,
            patch("whisper_anywhere.__main__.TextOutput") as output,
            patch("whisper_anywhere.__main__.Lock"),
            patch(
                "whisper_anywhere.transcribe.load_engine", return_value=_StubEngine()
            ),
            patch.object(Daemon, "run", fake_run),
        ):
            main()

        select.assert_called_once()
        check_deps.assert_called_once()
        assert check_deps.call_args.args[1] is selection
        output.assert_called_once_with(False, inserter)
