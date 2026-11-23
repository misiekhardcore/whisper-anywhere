"""The only module that imports GTK, and only inside the tray process."""

from importlib import resources
from typing import TYPE_CHECKING, Callable

from .appearance import DAEMON_STOPPED, ICON_DIMMED, Appearance
from .notifier_host import WATCHER_NAME, NotifierHost

if TYPE_CHECKING:
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk

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

    def __init__(self) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, GLib, Gtk

        self._glib: "GLib" = GLib
        self._gtk: "Gtk" = Gtk
        self._quit_handler: Callable[[], None] | None = None

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
        quit_item = Gtk.MenuItem(label=QUIT_LABEL)
        quit_item.connect("activate", self._activate_quit)

        menu = Gtk.Menu()
        menu.append(self._status_item)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(quit_item)
        menu.show_all()
        self._indicator.set_menu(menu)

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

    def _activate_quit(self, _item: object) -> None:
        if self._quit_handler is not None:
            self._quit_handler()
