"""What the daemon is doing, published on a socket the tray can observe."""

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .config import Config

STATUS_SOCKET_PATH = os.path.join(Config.runtime_dir(), "state.sock")


class DaemonState(str, Enum):
    LOADING = "loading"
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


@dataclass(frozen=True)
class DaemonStatus:
    """One snapshot of the daemon: what it does and the note the menu shows."""

    state: DaemonState = DaemonState.IDLE
    note: str | None = None

    def encode(self) -> bytes:
        payload = {"state": self.state.value, "note": self.note}
        return (json.dumps(payload) + "\n").encode()

    @classmethod
    def decode(cls, line: str | bytes) -> "DaemonStatus":
        payload = json.loads(line)
        return cls(DaemonState(payload["state"]), payload.get("note"))


class StatePublisher(Protocol):
    def publish(self, state: DaemonState, note: str | None = None) -> None: ...


class StatusChannel(StatePublisher, Protocol):
    """The publisher the daemon runs against: it also carries the quit request."""

    @property
    def quit_requested(self) -> asyncio.Event: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class NullStatus:
    """A publisher for code that has no socket to serve, such as unit tests."""

    def __init__(self) -> None:
        self._quit = asyncio.Event()

    @property
    def quit_requested(self) -> asyncio.Event:
        return self._quit

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def publish(self, state: DaemonState, note: str | None = None) -> None:
        return None


def _is_quit_command(line: bytes) -> bool:
    text = line.decode(errors="replace").strip()
    if text == "quit":
        return True
    try:
        return json.loads(text).get("command") == "quit"
    except (ValueError, AttributeError):
        return False


class StatusServer:
    """The newline-delimited JSON status socket served from the daemon's loop."""

    def __init__(self, path: str = STATUS_SOCKET_PATH) -> None:
        self._path = path
        self._status = DaemonStatus()
        self._clients: set[asyncio.StreamWriter] = set()
        self._quit = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None
        self._flushes: set[asyncio.Task] = set()

    @property
    def path(self) -> str:
        return self._path

    @property
    def status(self) -> DaemonStatus:
        return self._status

    @property
    def quit_requested(self) -> asyncio.Event:
        return self._quit

    async def start(self) -> None:
        self._remove_socket()
        self._server = await asyncio.start_unix_server(self._serve, path=self._path)

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
        # Close the clients first: their handlers are blocked reading, so
        # waiting for them before closing would never return.
        for writer in tuple(self._clients):
            self._drop(writer)
        if server is not None:
            await server.wait_closed()
        for flush in tuple(self._flushes):
            flush.cancel()
        self._flushes.clear()
        self._remove_socket()

    def publish(self, state: DaemonState, note: str | None = None) -> None:
        self._status = DaemonStatus(state, note)
        payload = self._status.encode()
        for writer in tuple(self._clients):
            try:
                writer.write(payload)
            except (OSError, RuntimeError):
                self._drop(writer)
        if self._clients:
            flush = asyncio.create_task(self._flush())
            self._flushes.add(flush)
            flush.add_done_callback(self._flushes.discard)

    async def _flush(self) -> None:
        for writer in tuple(self._clients):
            try:
                await writer.drain()
            except (OSError, RuntimeError):
                self._drop(writer)

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._clients.add(writer)
        try:
            try:
                writer.write(self._status.encode())
                await writer.drain()
            except (OSError, RuntimeError):
                # A client that sends a command and leaves at once never
                # reads the snapshot; its command may still be buffered.
                pass
            while True:
                line = await reader.readline()
                if not line:
                    break
                if _is_quit_command(line):
                    self._quit.set()
                    break
        except (OSError, RuntimeError):
            pass
        finally:
            self._drop(writer)

    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._clients.discard(writer)
        try:
            writer.close()
        except (OSError, RuntimeError):
            pass

    def _remove_socket(self) -> None:
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"Could not remove {self._path}: {exc}", file=sys.stderr)
