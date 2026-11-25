import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from .base import TextInserter
from .chord import PasteChord, WtypeChord, YdotoolChord
from .clipboard import (
    WL_CLIPBOARD_INSTALL,
    XCLIP_INSTALL,
    Clipboard,
    WaylandClipboard,
    X11Clipboard,
)
from .clipboard_inserter import ClipboardInserter
from .focused_window import CompositorWindowQuery

Which = Callable[[str], str | None]

WAYLAND_SESSION = "wayland"
X11_SESSION = "x11"
MISSING_TOOL_MESSAGE = (
    "No insertion tool found — install ydotool (sudo apt install ydotool) "
    "or wtype (sudo apt install wtype)"
)


@dataclass(frozen=True)
class InsertionSelection:
    """The insertion strategy resolved once at startup."""

    inserter: TextInserter | None
    description: str
    warning: str | None


def detect_session_type() -> str:
    session: str = os.environ.get("XDG_SESSION_TYPE", "")
    if not session and os.environ.get("WAYLAND_DISPLAY"):
        return WAYLAND_SESSION
    return session.lower()


def select_insertion(
    which: Which = shutil.which,
    session_type: str | None = None,
) -> InsertionSelection:
    session: str = (
        detect_session_type() if session_type is None else session_type.lower()
    )
    if which("ydotool"):
        chord: PasteChord = YdotoolChord()
    elif which("wtype"):
        chord = WtypeChord()
    else:
        return InsertionSelection(None, MISSING_TOOL_MESSAGE, None)

    if session == X11_SESSION:
        if which("xclip"):
            return _clipboard_selection(X11Clipboard(), "xclip", chord)
        return InsertionSelection(
            None,
            f"Clipboard insertion unavailable: xclip not found — {XCLIP_INSTALL}",
            None,
        )

    # Wayland is the documented backend for every other session type.
    if which("wl-copy") and which("wl-paste"):
        return _clipboard_selection(WaylandClipboard(), "wl-clipboard", chord)
    return InsertionSelection(
        None,
        "Clipboard insertion unavailable: wl-copy/wl-paste not found — "
        f"{WL_CLIPBOARD_INSTALL}",
        None,
    )


def _clipboard_selection(
    clipboard: Clipboard, backend: str, chord: PasteChord
) -> InsertionSelection:
    return InsertionSelection(
        ClipboardInserter(clipboard, chord, CompositorWindowQuery()),
        f"clipboard paste ({chord.TOOL} + {backend})",
        None,
    )
