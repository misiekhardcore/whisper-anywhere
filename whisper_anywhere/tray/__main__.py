import sys


def main() -> int:
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
