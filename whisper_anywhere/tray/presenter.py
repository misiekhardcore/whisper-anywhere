"""The toolkit-facing surface the tray controller drives."""

from typing import Callable, Protocol

from .appearance import Appearance

QuitHandler = Callable[[], None]


class TrayPresenter(Protocol):
    """The GTK indicator, hid behind a protocol so the tray runs headlessly."""

    def show(self, appearance: Appearance) -> None: ...

    def set_quit_handler(self, handler: QuitHandler) -> None: ...

    def run(self) -> None: ...

    def stop(self) -> None: ...
