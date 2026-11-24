"""The only module that imports GTK, and only inside the tray process."""

import sys
from importlib import resources
from typing import TYPE_CHECKING, Callable

from .appearance import DAEMON_STOPPED, ICON_DIMMED, Appearance
from .autostart import LoginAutostart, SubprocessRunner
from .notifier_host import WATCHER_NAME, NotifierHost

if TYPE_CHECKING:
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk

START_AT_LOGIN_LABEL = "Start at login"
QUIT_LABEL = "Quit whisper anywhere"


def _icon_theme_directory() -> str:
    """The theme root the panel host searches; it resolves the icon, not us."""
    return str(resources.files("whisper_anywhere").joinpath("icons"))


def _status_notifier_host_present() -> bool:
    """Whether the session bus currently owns the StatusNotifier watcher name."""
    from gi.repository import Gio, GLib

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (WATCHER_NAME,)),
            GLib.VariantType.new("(b)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return bool(reply.unpack()[0])
    except GLib.Error:
        return False


class GtkPresenter:
    """One AppIndicator whose icon and status line follow the daemon."""

    def __init__(self, autostart: LoginAutostart | None = None) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, GLib, Gtk

        self._glib: "GLib" = GLib
        self._gtk: "Gtk" = Gtk
        self._quit_handler: Callable[[], None] | None = None
        self._autostart: LoginAutostart = autostart or LoginAutostart(
            SubprocessRunner()
        )
        self._syncing_autostart: bool = False

        self._indicator: "AyatanaAppIndicator3.Indicator" = (
            AyatanaAppIndicator3.Indicator.new(
                "whisper-anywhere",
                ICON_DIMMED,
                AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
        )
        self._indicator.set_icon_theme_path(_icon_theme_directory())
        self._indicator_status = AyatanaAppIndicator3.IndicatorStatus.ACTIVE
        self._host = NotifierHost(
            register=self._register_with_host,
            host_present=_status_notifier_host_present,
            schedule_retry=GLib.timeout_add,
        )
        self._host.start()

        self._status_item = Gtk.MenuItem(label=DAEMON_STOPPED.status_text)
        self._status_item.set_sensitive(False)
        self._autostart_item = Gtk.CheckMenuItem(label=START_AT_LOGIN_LABEL)
        self._autostart_item.connect("toggled", self._activate_autostart)
        quit_item = Gtk.MenuItem(label=QUIT_LABEL)
        quit_item.connect("activate", self._activate_quit)

        menu = Gtk.Menu()
        menu.append(self._status_item)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._autostart_item)
        menu.append(quit_item)
        menu.show_all()
        self._indicator.set_menu(menu)
        self._watch_menu_opens()
        self._refresh_autostart()

    def set_quit_handler(self, handler: Callable[[], None]) -> None:
        self._quit_handler = handler

    def show(self, appearance: Appearance) -> None:
        self._glib.idle_add(self._apply, appearance)

    def run(self) -> None:
        self._gtk.main()

    def stop(self) -> None:
        self._gtk.main_quit()

    def _register_with_host(self) -> None:
        """Announce the indicator so the status-notifier host draws it."""
        self._indicator.set_status(self._indicator_status)

    def _apply(self, appearance: Appearance) -> bool:
        self._indicator.set_icon_full(appearance.icon_name, appearance.status_text)
        self._status_item.set_label(appearance.status_text)
        return False

    def _watch_menu_opens(self) -> None:
        """A panel asks the exported dbusmenu AboutToShow before drawing it."""
        try:
            server = self._indicator.get_property("dbus-menu-server")
            root = server.get_property("root-node")
        except (AttributeError, ImportError) as exc:
            print(
                f"Cannot watch menu opens ({exc}); Start at login may go stale.",
                file=sys.stderr,
            )
            return
        root.connect("about-to-show", self._refresh_autostart)

    def _refresh_autostart(self, _menu: object = None) -> None:
        """Re-read the units so the check mark is never stale, or hide it."""
        enabled = self._autostart.is_enabled()
        if enabled is None:
            self._autostart_item.hide()
            return
        self._syncing_autostart = True
        try:
            self._autostart_item.set_active(enabled)
        finally:
            self._syncing_autostart = False
        self._autostart_item.show()

    def _activate_autostart(self, item: "Gtk.CheckMenuItem") -> None:
        if self._syncing_autostart:
            return
        self._autostart.set_enabled(item.get_active())

    def _activate_quit(self, _item: object) -> None:
        if self._quit_handler is not None:
            self._quit_handler()
