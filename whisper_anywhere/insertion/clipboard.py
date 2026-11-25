import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

WL_CLIPBOARD_INSTALL = "install it: sudo apt install wl-clipboard"
XCLIP_INSTALL = "install it: sudo apt install xclip"
_READ_TIMEOUT_SECONDS = 2


class ClipboardError(Exception):
    """The clipboard tool is missing or refused the write."""


@dataclass(frozen=True)
class ClipboardContent:
    """What the clipboard currently holds; ``text`` is None for non-text payloads."""

    text: str | None


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
        types: str | None = _read_detached(["wl-paste", "--list-types"])
        if types is None or "text/" not in types:
            return ClipboardContent(None)
        return ClipboardContent(_read_detached(["wl-paste", "--no-newline"]))

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

class X11Clipboard(Clipboard):
    """`xclip` on the CLIPBOARD selection, the X11 backend."""

    _SELECTION: list[str] = ["xclip", "-selection", "clipboard"]

    def read(self) -> ClipboardContent:
        targets: str | None = _read_detached(self._SELECTION + ["-t", "TARGETS", "-o"])
        if targets is None or not _offers_text(targets):
            return ClipboardContent(None)
        return ClipboardContent(_read_detached(self._SELECTION + ["-o"]))

    def write(self, text: str) -> None:
        try:
            result = subprocess.run(
                self._SELECTION + ["-i"],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ClipboardError(f"xclip not found — {XCLIP_INSTALL}") from exc
        if result.returncode != 0:
            raise ClipboardError(f"xclip failed (exit {result.returncode})")


_TEXT_TARGETS: frozenset[str] = frozenset({"UTF8_STRING", "STRING", "TEXT"})


def _offers_text(targets: str) -> bool:
    """True when the advertised selection targets include a text flavour."""
    names: set[str] = {name.strip() for name in targets.splitlines() if name.strip()}
    return any(
        name in _TEXT_TARGETS or name.startswith("text/") for name in names
    )


def _read_detached(command: list[str]) -> str | None:
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
