"""The real GTK presenter, driven through its menu against a real status socket.

The other tray tests fake the presenter; this one imports GTK for real. It
skips without a display or the AppIndicator typelib, as CI has neither.
"""

import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Callable

import pytest

from whisper_anywhere.state import DaemonState, StatusServer
from whisper_anywhere.tray.appearance import (
    ICON_DIMMED,
    ICON_IDLE,
    ICON_PROCESSING,
    ICON_RECORDING,
)
from whisper_anywhere.tray.controller import TrayController


def _gtk_available() -> bool:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, Gtk  # noqa: F401

        available, _ = Gtk.init_check()
        return available
    except (ImportError, ValueError, RuntimeError):
        return False


pytestmark = pytest.mark.skipif(
    not _gtk_available(), reason="needs a display with GTK and AppIndicator"
)


class _ThreadedDaemon:
    """A real StatusServer on a background loop, standing in for the daemon."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.loop = asyncio.new_event_loop()
        self.server = StatusServer(str(path))
        self.quit_seen = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._call(self.server.start())
        self.loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._watch_quit())
        )

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _call(self, coro) -> object:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(5)

    async def _watch_quit(self) -> None:
        await self.server.quit_requested.wait()
        self.quit_seen.set()
        await self.server.close()

    def publish(self, state: DaemonState) -> None:
        self.loop.call_soon_threadsafe(self.server.publish, state)

    def close(self) -> None:
        try:
            self._call(self.server.close())
        except (RuntimeError, OSError):
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(2)
        self.loop.close()


class _Menu:
    """The real AppIndicator menu, read through its public GTK accessors."""

    def __init__(self, presenter) -> None:
        self._indicator = presenter._indicator

    @property
    def icon(self) -> str | None:
        return self._indicator.get_icon()

    def _items(self) -> list:
        return self._indicator.get_menu().get_children()

    @property
    def status_text(self) -> str:
        return self._items()[0].get_label()

    @property
    def status_sensitive(self) -> bool:
        return self._items()[0].get_sensitive()

    def quit_item(self):
        for item in self._items():
            if item.get_label() == "Quit whisper anywhere":
                return item
        raise AssertionError(
            f"no quit item in {[i.get_label() for i in self._items()]}"
        )


class _Sequencer:
    """Advances a list of (action, probe) steps from a GLib timeout."""

    def __init__(
        self, steps: list[tuple[Callable[[], None] | None, Callable[[], bool]]], abort
    ) -> None:
        self._steps = list(steps)
        self._abort = abort
        self._deadline = time.monotonic() + 10
        self.failure: BaseException | None = None

    def tick(self) -> bool:
        if self.failure is not None:
            return False
        try:
            while self._steps:
                action, probe = self._steps[0]
                if action is not None:
                    if probe is None:
                        self._steps.pop(0)
                    else:
                        self._steps[0] = (None, probe)
                    action()
                    return True
                if not probe():
                    if time.monotonic() > self._deadline:
                        raise AssertionError(
                            "timed out waiting for the next tray state"
                        )
                    return True
                self._steps.pop(0)
            return False
        except BaseException as exc:
            self.failure = exc
            self._abort()
            return False


def test_the_indicator_exports_an_icon_theme_the_host_can_resolve() -> None:
    """The host resolves the icon name itself, so the theme path must carry it."""
    from gi.repository import Gtk

    from whisper_anywhere.tray.gtk import GtkPresenter

    presenter = GtkPresenter()
    theme_path = presenter._indicator.get_icon_theme_path()
    assert theme_path, "the indicator exports no icon theme path"

    theme = Gtk.IconTheme.new()
    theme.set_search_path([theme_path])
    for icon in (ICON_IDLE, ICON_RECORDING, ICON_PROCESSING, ICON_DIMMED):
        for scale, directory in ((1, "22x22"), (2, "44x44")):
            info = theme.lookup_icon_for_scale(icon, 22, scale, 0)
            assert info is not None, f"{icon} does not resolve at scale {scale}"
            assert Path(info.get_filename()).parent.parent.name == directory


def test_real_gtk_tray_follows_states_and_quits(tmp_path: Path) -> None:
    from gi.repository import GLib

    from whisper_anywhere.tray.gtk import GtkPresenter

    daemon = _ThreadedDaemon(tmp_path / "state.sock")
    presenter = GtkPresenter()
    menu = _Menu(presenter)
    controller = TrayController(
        presenter, str(daemon.path), retry_delay=0.02, quit_timeout=2
    )
    try:
        # Before the first state arrives the panel is dimmed and says so.
        assert menu.icon == ICON_DIMMED
        assert menu.status_text == "daemon stopped"
        assert menu.status_sensitive is False
        assert menu.quit_item().get_sensitive() is True

        steps = [
            (None, lambda: menu.icon == ICON_IDLE and menu.status_text == "Idle"),
            (lambda: daemon.publish(DaemonState.RECORDING), None),
            (
                None,
                lambda: menu.icon == ICON_RECORDING and menu.status_text == "Recording",
            ),
            (lambda: daemon.publish(DaemonState.PROCESSING), None),
            (
                None,
                lambda: (
                    menu.icon == ICON_PROCESSING and menu.status_text == "Processing"
                ),
            ),
            (lambda: daemon.publish(DaemonState.IDLE), None),
            (None, lambda: menu.icon == ICON_IDLE and menu.status_text == "Idle"),
            # Click the real menu item; the controller sends quit, waits for the
            # daemon and stops the GTK loop, so run() returns here.
            (lambda: menu.quit_item().emit("activate"), None),
        ]
        sequencer = _Sequencer(steps, abort=controller.quit)
        GLib.timeout_add(20, sequencer.tick)

        def give_up() -> bool:
            if sequencer.failure is None:
                sequencer.failure = AssertionError("the tray never quit")
                controller.quit()
            return False

        GLib.timeout_add(10_000, give_up)

        controller.run()

        if sequencer.failure is not None:
            raise sequencer.failure
        assert daemon.quit_seen.wait(3), "the daemon never received the quit command"
        assert not daemon.path.exists(), "the daemon socket outlived the quit"
    finally:
        daemon.close()
