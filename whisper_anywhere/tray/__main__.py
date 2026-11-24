import sys

GTK_PACKAGES = "python3-gi gir1.2-ayatanaappindicator3-0.1"


def _missing_gtk_dependency() -> str | None:
    """The first import or typelib failure behind the tray, if any."""
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        return str(exc)
    return None


def main() -> int:
    missing = _missing_gtk_dependency()
    if missing is not None:
        print(
            f"Missing GTK dependencies ({missing}). Run: sudo apt install {GTK_PACKAGES}",
            file=sys.stderr,
        )
        return 1

    try:
        from .gtk import GtkPresenter

        presenter = GtkPresenter()
    except Exception as exc:
        print(f"Tray unavailable: {exc}", file=sys.stderr)
        return 1

    from .controller import TrayController

    TrayController(presenter).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
