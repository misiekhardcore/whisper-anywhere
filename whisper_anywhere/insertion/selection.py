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
    chord: PasteChord | None = _select_chord(which)
    clipboard_problem: str | None = _clipboard_problem(session, which)

    if chord is not None and clipboard_problem is None:
        return InsertionSelection(
            ClipboardInserter(WaylandClipboard(), chord),
            f"clipboard paste ({chord.TOOL} + wl-clipboard)",
            None,
        )
    if chord is not None:
        return InsertionSelection(
            TypingInserter(chord.TOOL),
            f"typing ({chord.TOOL})",
            f"Clipboard insertion unavailable: {clipboard_problem}. "
            "Falling back to typing insertion.",
        )
    return InsertionSelection(
        None,
        "no insertion tool: install ydotool (sudo apt install ydotool) "
        "or wtype (sudo apt install wtype)",
        None,
    )


def _select_chord(which: Which) -> PasteChord | None:
    if which("ydotool"):
        return YdotoolChord()
    if which("wtype"):
        return WtypeChord()
    return None


def _clipboard_problem(session: str, which: Which) -> str | None:
    if session != WAYLAND_SESSION:
        return "the Wayland clipboard backend needs a Wayland session"
    if not which("wl-copy") or not which("wl-paste"):
        return f"wl-copy/wl-paste not found — {WL_CLIPBOARD_INSTALL}"
    return None
