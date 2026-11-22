import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

WL_CLIPBOARD_INSTALL = "install it: sudo apt install wl-clipboard"
_READ_TIMEOUT_SECONDS = 2


class ClipboardError(Exception):
    """The clipboard tool is missing or refused the write."""


@dataclass(frozen=True)
class ClipboardContent:
    """What the clipboard currently holds; ``text`` is None for non-text payloads."""

    text: str | None

    @property
    def is_text(self) -> bool:
        return self.text is not None


class Clipboard(ABC):
    @abstractmethod
    def read(self) -> ClipboardContent:
        """The current clipboard content; non-text and failures read as no text."""

    @abstractmethod
    def write(self, text: str) -> None:
        """Replace the clipboard with ``text``; raises ``ClipboardError``."""


class WaylandClipboard(Clipboard):
    """`wl-copy` / `wl-paste` from wl-clipboard, the Wayland backend."""

    def read(self) -> ClipboardContent:
        types: str | None = self._capture(["wl-paste", "--list-types"])
        if types is None or "text/" not in types:
            return ClipboardContent(None)
        return ClipboardContent(self._capture(["wl-paste", "--no-newline"]))

    def write(self, text: str) -> None:
        try:
            result = subprocess.run(
                ["wl-copy"],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ClipboardError(f"wl-copy not found — {WL_CLIPBOARD_INSTALL}") from exc
        if result.returncode != 0:
            raise ClipboardError(f"wl-copy failed (exit {result.returncode})")

    @staticmethod
    def _capture(command: list[str]) -> str | None:
        """Query the clipboard detached from our streams: a forked selection
        owner could otherwise hold an inherited pipe open forever.
        """
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_READ_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout
