"""Follows the daemon's status socket and drives the presenter."""

import threading
import time

from ..state import STATUS_SOCKET_PATH, DaemonStatus
from .appearance import DAEMON_STOPPED, Appearance, appearance_for
from .client import StatusClient, send_quit
from .presenter import TrayPresenter

RETRY_DELAY_S = 1.0
QUIT_TIMEOUT_S = 5.0


class TrayController:
    def __init__(
        self,
        presenter: TrayPresenter,
        socket_path: str = STATUS_SOCKET_PATH,
        retry_delay: float = RETRY_DELAY_S,
        quit_timeout: float = QUIT_TIMEOUT_S,
    ) -> None:
        self._presenter = presenter
        self._socket_path = socket_path
        self._retry_delay = retry_delay
        self._quit_timeout = quit_timeout
        self._stopping = threading.Event()
        self._quitting = threading.Event()
        self._showing: Appearance | None = None
        self._client: StatusClient | None = None
        self._reader: threading.Thread | None = None

    def run(self) -> None:
        """Serve the panel until Quit, or until the presenter's loop ends."""
        self._presenter.set_quit_handler(self.quit)
        self._show(DAEMON_STOPPED)
        self._reader = threading.Thread(
            target=self._follow, name="whisper-anywhere-status", daemon=True
        )
        self._reader.start()
        try:
            self._presenter.run()
        finally:
            self._stopping.set()
            self._close_client()
            if self._reader is not None:
                self._reader.join(timeout=self._retry_delay + 1)

    def quit(self) -> None:
        """Stop the daemon, wait for it to exit and take the tray with it."""
        if self._quitting.is_set():
            return
        self._quitting.set()
        self._stopping.set()
        self._close_client()
        try:
            send_quit(self._socket_path)
        except OSError:
            pass
        self._wait_for_daemon_exit()
        self._presenter.stop()

    def _follow(self) -> None:
        while not self._stopping.is_set():
            try:
                client = StatusClient(self._socket_path).connect()
            except OSError:
                self._show(DAEMON_STOPPED)
                self._stopping.wait(self._retry_delay)
                continue

            self._client = client
            try:
                while not self._stopping.is_set():
                    status: DaemonStatus | None = client.read_status()
                    if status is not None:
                        self._show(appearance_for(status))
            except (ConnectionError, OSError):
                self._show(DAEMON_STOPPED)
                self._stopping.wait(self._retry_delay)
            finally:
                client.close()
                self._client = None

    def _wait_for_daemon_exit(self) -> None:
        deadline = time.monotonic() + self._quit_timeout
        while time.monotonic() < deadline:
            if self._daemon_gone():
                return
            time.sleep(0.05)

    def _daemon_gone(self) -> bool:
        try:
            StatusClient(self._socket_path, poll_timeout=0.1).connect().close()
        except OSError:
            return True
        return False

    def _show(self, appearance: Appearance) -> None:
        if appearance == self._showing:
            return
        self._showing = appearance
        self._presenter.show(appearance)

    def _close_client(self) -> None:
        client = self._client
        if client is not None:
            client.close()
