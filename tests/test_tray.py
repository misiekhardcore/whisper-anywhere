import asyncio
import threading
from pathlib import Path

import pytest

from whisper_anywhere.state import DaemonState, DaemonStatus, StatusServer
from whisper_anywhere.tray.appearance import (
    DAEMON_STOPPED,
    ICON_DIMMED,
    ICON_IDLE,
    ICON_PROCESSING,
    ICON_RECORDING,
    Appearance,
    appearance_for,
)
from whisper_anywhere.tray.client import StatusClient
from whisper_anywhere.tray.controller import TrayController

TIMEOUT = 5


def _idle() -> Appearance:
    return Appearance(ICON_IDLE, "Idle")


def _recording() -> Appearance:
    return Appearance(ICON_RECORDING, "Recording")


def _processing() -> Appearance:
    return Appearance(ICON_PROCESSING, "Processing")


class TestAppearance:
    def test_idle_is_a_neutral_icon_naming_the_state(self) -> None:
        assert appearance_for(DaemonStatus(DaemonState.IDLE)) == _idle()

    def test_recording_is_red(self) -> None:
        assert appearance_for(DaemonStatus(DaemonState.RECORDING)) == _recording()

    def test_processing_is_green(self) -> None:
        assert appearance_for(DaemonStatus(DaemonState.PROCESSING)) == _processing()

    def test_loading_and_an_absent_daemon_share_the_dimmed_icon(self) -> None:
        starting: Appearance = appearance_for(DaemonStatus(DaemonState.LOADING))

        assert starting.icon_name == DAEMON_STOPPED.icon_name == ICON_DIMMED
        assert starting.status_text == "Starting"
        assert DAEMON_STOPPED.status_text == "daemon stopped"

    def test_a_failure_note_joins_the_status_line(self) -> None:
        appearance: Appearance = appearance_for(
            DaemonStatus(DaemonState.IDLE, "Last dictation failed")
        )

        assert appearance.icon_name == ICON_IDLE
        assert appearance.status_text == "Idle - Last dictation failed"


class _FakePresenter:
    """Records appearances and lets a test click Quit from another thread."""

    def __init__(self) -> None:
        self.shown: list[Appearance] = []
        self.stopped: bool = False
        self._changed = threading.Condition()
        self._exited = threading.Event()
        self._quit_handler: object = None

    def show(self, appearance: Appearance) -> None:
        with self._changed:
            if not self.shown or self.shown[-1] != appearance:
                self.shown.append(appearance)
            self._changed.notify_all()

    def wait_for(self, appearance: Appearance, timeout: float = TIMEOUT) -> None:
        with self._changed:
            if not self._changed.wait_for(
                lambda: appearance in self.shown, timeout=timeout
            ):
                raise AssertionError(f"{appearance} never shown; saw {self.shown}")

    def wait_for_last(self, appearance: Appearance, timeout: float = TIMEOUT) -> None:
        with self._changed:
            if not self._changed.wait_for(
                lambda: bool(self.shown) and self.shown[-1] == appearance,
                timeout=timeout,
            ):
                raise AssertionError(f"{appearance} never last; saw {self.shown}")

    def set_quit_handler(self, handler: object) -> None:
        self._quit_handler = handler

    def trigger_quit(self) -> None:
        assert callable(self._quit_handler)
        self._quit_handler()

    def run(self) -> None:
        self._exited.wait(TIMEOUT)

    def stop(self) -> None:
        self.stopped = True
        self._exited.set()


class _Tray:
    """The controller running in a thread against a real status socket."""

    def __init__(self, path: Path, retry_delay: float = 0.02) -> None:
        self.path = path
        self.presenter = _FakePresenter()
        self.controller = TrayController(
            self.presenter,
            str(path),
            retry_delay=retry_delay,
            quit_timeout=2.0,
        )
        self.task: asyncio.Task | None = None

    async def __aenter__(self) -> "_Tray":
        self.task = asyncio.create_task(asyncio.to_thread(self.controller.run))
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self.presenter.stopped:
            await asyncio.to_thread(self.controller.quit)
        if self.task is not None:
            await asyncio.wait_for(self.task, TIMEOUT)


async def _daemon(path: Path) -> StatusServer:
    server = StatusServer(str(path))
    await server.start()
    return server


async def _wait_for(presenter: _FakePresenter, appearance: Appearance) -> None:
    await asyncio.wait_for(asyncio.to_thread(presenter.wait_for, appearance), TIMEOUT)


@pytest.mark.asyncio
class TestTrayFollowsTheDaemon:
    async def test_the_absent_appearance_shows_before_the_first_state(
        self, tmp_path: Path
    ) -> None:
        async with _Tray(tmp_path / "state.sock") as tray:
            await _wait_for(tray.presenter, DAEMON_STOPPED)

            assert tray.presenter.shown[0] == DAEMON_STOPPED

    async def test_recording_processing_and_idle_reach_the_presenter(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "state.sock"
        server = await _daemon(path)
        async with _Tray(path) as tray:
            await _wait_for(tray.presenter, _idle())

            server.publish(DaemonState.RECORDING)
            await _wait_for(tray.presenter, _recording())

            server.publish(DaemonState.PROCESSING)
            await _wait_for(tray.presenter, _processing())

            server.publish(DaemonState.IDLE)
            await _wait_for(tray.presenter, _idle())
            await server.close()

    async def test_a_lost_daemon_falls_back_to_the_dimmed_appearance(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "state.sock"
        server = await _daemon(path)
        async with _Tray(path) as tray:
            await _wait_for(tray.presenter, _idle())

            await server.close()
            await asyncio.wait_for(
                asyncio.to_thread(tray.presenter.wait_for_last, DAEMON_STOPPED),
                TIMEOUT,
            )

            assert tray.presenter.shown[-1] == DAEMON_STOPPED

    async def test_the_tray_reconnects_when_the_daemon_returns(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "state.sock"
        server = await _daemon(path)
        async with _Tray(path) as tray:
            await _wait_for(tray.presenter, _idle())
            await server.close()
            await _wait_for(tray.presenter, DAEMON_STOPPED)

            server = await _daemon(path)
            server.publish(DaemonState.RECORDING)
            await _wait_for(tray.presenter, _recording())

            assert tray.presenter.shown[-1] == _recording()
            await server.close()

    async def test_quit_asks_the_daemon_to_stop_and_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "state.sock"
        server = await _daemon(path)
        async with _Tray(path) as tray:
            await _wait_for(tray.presenter, _idle())

            quitting = asyncio.create_task(
                asyncio.to_thread(tray.presenter.trigger_quit)
            )
            await asyncio.wait_for(server.quit_requested.wait(), TIMEOUT)
            await server.close()
            await asyncio.wait_for(quitting, TIMEOUT)
            await asyncio.wait_for(tray.task, TIMEOUT)

            assert tray.presenter.stopped


class TestIcons:
    def test_every_appearance_icon_ships_in_panel_and_hidpi_sizes(self) -> None:
        from importlib import resources

        icons = resources.files("whisper_anywhere").joinpath("icons")
        for icon in (ICON_IDLE, ICON_RECORDING, ICON_PROCESSING, ICON_DIMMED):
            for suffix in ("", "@2x"):
                assert icons.joinpath(f"{icon}{suffix}.png").is_file(), icon


@pytest.mark.asyncio
class TestStatusClient:
    async def test_reads_the_snapshot_then_the_next_change(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "state.sock"
        server = await _daemon(path)
        client = await asyncio.to_thread(StatusClient(str(path)).connect)
        try:
            first = await asyncio.to_thread(client.read_status)
            assert first is not None
            assert first.state == DaemonState.IDLE

            server.publish(DaemonState.PROCESSING)
            second = await asyncio.to_thread(client.read_status)
            assert second is not None
            assert second.state == DaemonState.PROCESSING
        finally:
            client.close()
            await server.close()
