import asyncio
import sys
import threading
import types
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


class TestTrayEntryPoint:
    def test_names_the_gtk_and_appindicator_packages_when_absent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from whisper_anywhere.tray.__main__ import main

        monkeypatch.setitem(sys.modules, "gi", None)

        assert main() == 1
        error: str = capsys.readouterr().err
        assert "python3-gi" in error
        assert "gir1.2-ayatanaappindicator3-0.1" in error

    def test_names_the_packages_when_a_typelib_namespace_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from whisper_anywhere.tray.__main__ import main

        class _FakeGi(types.ModuleType):
            def require_version(self, namespace: str, version: str) -> None:
                raise ValueError(f"Namespace {namespace} not available")

        monkeypatch.setitem(sys.modules, "gi", _FakeGi("gi"))

        assert main() == 1
        error: str = capsys.readouterr().err
        assert "gir1.2-ayatanaappindicator3-0.1" in error


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


DARK_PANEL = (29, 29, 29, 255)
LIGHT_PANEL = (240, 240, 240, 255)
# Overall contrast ratio a pixel needs against the panel to count as drawn.
VISIBLE_CONTRAST = 3.0
# Share of a region that must stay drawn: a whole part cannot fade out.
VISIBLE_SHARE = 0.05
# The capsule and the stand are checked apart, since the stand once vanished.
REGIONS = {"capsule": (0.05, 0.02, 0.95, 0.52), "stand": (0.05, 0.62, 0.95, 0.93)}


def _relative_luminance(pixel: tuple[int, ...]) -> float:
    def linear(channel: int) -> float:
        ratio = channel / 255
        return ratio / 12.92 if ratio <= 0.04045 else ((ratio + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in pixel[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(pixel: tuple[int, ...], background: tuple[int, ...]) -> float:
    lighter, darker = sorted(
        (_relative_luminance(pixel), _relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _visible_pixels(
    icon, background: tuple[int, ...], region: tuple[float, ...]
) -> int:
    """How many pixels of one region stay visible once painted on that panel."""
    from PIL import Image

    size = icon.width
    panel = Image.new("RGBA", icon.size, background)
    painted = Image.alpha_composite(panel, icon.convert("RGBA"))
    box = (
        round(region[0] * size),
        round(region[1] * size),
        round(region[2] * size),
        round(region[3] * size),
    )
    return sum(
        1
        for pixel in painted.crop(box).getdata()
        if _contrast(pixel, background) >= VISIBLE_CONTRAST
    )


class TestIcons:
    def test_every_appearance_icon_ships_in_panel_and_hidpi_sizes(self) -> None:
        from importlib import resources

        theme = resources.files("whisper_anywhere").joinpath("icons", "hicolor")
        assert theme.joinpath("index.theme").is_file()
        for icon in (ICON_IDLE, ICON_RECORDING, ICON_PROCESSING, ICON_DIMMED):
            for size in (22, 44):
                path = theme.joinpath(f"{size}x{size}", "apps", f"{icon}.png")
                assert path.is_file(), path

    @pytest.mark.parametrize("size", [22, 44])
    @pytest.mark.parametrize("background", [DARK_PANEL, LIGHT_PANEL])
    def test_every_icon_stays_visible_on_any_panel_background(
        self, size: int, background: tuple[int, ...]
    ) -> None:
        """The panel may be light or dark, and it draws our pixels unchanged."""
        from importlib import resources

        from PIL import Image

        theme = resources.files("whisper_anywhere").joinpath(
            "icons", "hicolor", f"{size}x{size}", "apps"
        )
        for icon in (ICON_IDLE, ICON_RECORDING, ICON_PROCESSING, ICON_DIMMED):
            with theme.joinpath(f"{icon}.png").open("rb") as icon_file:
                image = Image.open(icon_file)
                for region, box in REGIONS.items():
                    area = (box[2] - box[0]) * size * (box[3] - box[1]) * size
                    required = round(area * VISIBLE_SHARE)
                    visible = _visible_pixels(image, background, box)
                    assert visible >= required, (
                        f"{icon} at {size}px has only {visible} visible {region} "
                        f"pixels on {background}, needs {required}"
                    )


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
