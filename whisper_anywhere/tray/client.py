"""A blocking client for the daemon's newline-delimited status socket."""

import socket

from ..state import DaemonStatus

QUIT_COMMAND = b'{"command": "quit"}\n'


class StatusClient:
    def __init__(self, path: str, poll_timeout: float = 0.5) -> None:
        self._path = path
        self._poll_timeout = poll_timeout
        self._socket: socket.socket | None = None
        self._buffer = b""

    def connect(self) -> "StatusClient":
        socket_handle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_handle.settimeout(self._poll_timeout)
        try:
            socket_handle.connect(self._path)
        except OSError:
            socket_handle.close()
            raise
        self._socket = socket_handle
        return self

    def read_status(self) -> DaemonStatus | None:
        """Return the next status, or None when no complete line arrived yet."""
        if self._socket is None:
            raise ConnectionError("not connected")
        while b"\n" not in self._buffer:
            try:
                chunk = self._socket.recv(4096)
            except socket.timeout:
                return None
            except OSError as exc:
                raise ConnectionError(str(exc)) from exc
            if not chunk:
                raise ConnectionError("the daemon closed the socket")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return DaemonStatus.decode(line)

    def send_quit(self) -> None:
        if self._socket is None:
            raise ConnectionError("not connected")
        try:
            self._socket.sendall(QUIT_COMMAND)
        except OSError as exc:
            raise ConnectionError(str(exc)) from exc

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.close()
        finally:
            self._socket = None

    def __enter__(self) -> "StatusClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def send_quit(path: str, timeout: float = 0.5) -> None:
    """Ask the daemon to stop, on a connection of its own."""
    with StatusClient(path, poll_timeout=timeout) as client:
        client.connect()
        # Read the snapshot first so the daemon's write completes before we go.
        try:
            client.read_status()
        except ConnectionError:
            pass
        client.send_quit()
