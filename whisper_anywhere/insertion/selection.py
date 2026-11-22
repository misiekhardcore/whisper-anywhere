import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from .base import TextInserter
from .chord import PasteChord, WtypeChord, YdotoolChord
from .clipboard import WL_CLIPBOARD_INSTALL, WaylandClipboard
from .clipboard_inserter import ClipboardInserter
from .typing import TypingInserter

Which = Callable[[str], str | None]

WAYLAND_SESSION = "wayland"
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

    if session != WAYLAND_SESSION:
        clipboard_problem: str = "the Wayland clipboard backend needs a Wayland session"
    elif not which("wl-copy") or not which("wl-paste"):
        clipboard_problem = f"wl-copy/wl-paste not found — {WL_CLIPBOARD_INSTALL}"
    else:
        return InsertionSelection(
            ClipboardInserter(WaylandClipboard(), chord),
            f"clipboard paste ({chord.TOOL} + wl-clipboard)",
            None,
        )
    return InsertionSelection(
        TypingInserter(chord.TOOL),
        f"typing ({chord.TOOL})",
        f"Clipboard insertion unavailable: {clipboard_problem}. "
        "Falling back to typing insertion.",
    )
