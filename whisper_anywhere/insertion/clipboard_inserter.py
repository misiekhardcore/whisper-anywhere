import sys
from collections.abc import Callable
from time import sleep

from .base import TextInserter
from .chord import ChordError, PasteChord
from .clipboard import Clipboard, ClipboardError
from .focused_window import FocusedWindowQuery

# How long the paste chord gets to land before the clipboard is touched again.
_SETTLE_DELAY_SECONDS = 0.2


class ClipboardInserter(TextInserter):
    """Pastes the transcript through the clipboard, then puts the old text back."""

    def __init__(
        self,
        clipboard: Clipboard,
        chord: PasteChord,
        focused_window: FocusedWindowQuery,
        pause: Callable[[float], None] = sleep,
    ) -> None:
        self._clipboard = clipboard
        self._chord = chord
        self._focused_window = focused_window
        self._pause = pause

    def insert_text(self, text: str) -> bool:
        if not text:
            return False
        previous_text: str | None = self._clipboard.read().text
        if not self._paste(text):
            return False
        self._restore(previous_text, text)
        return True

    def _paste(self, text: str) -> bool:
        try:
            self._clipboard.write(text)
        except ClipboardError as exc:
            print(f"Clipboard insertion failed: {exc}", file=sys.stderr)
            return False
        try:
            self._chord.send(terminal=self._focused_window.is_terminal())
        except ChordError as exc:
            print(
                f"Paste chord failed: {exc} — transcript left on the clipboard",
                file=sys.stderr,
            )
            return False
        return True

    def _restore(self, previous_text: str | None, text: str) -> None:
        if previous_text is None:
            return
        self._pause(_SETTLE_DELAY_SECONDS)
        if self._clipboard.read().text != text:
            return
        try:
            self._clipboard.write(previous_text)
        except ClipboardError as exc:
            print(
                f"Clipboard restore failed: {exc} — transcript left on the clipboard",
                file=sys.stderr,
            )
