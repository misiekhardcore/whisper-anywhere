import sys
from collections.abc import Callable
from time import sleep

from .base import TextInserter
from .chord import ChordError, PasteChord
from .clipboard import Clipboard, ClipboardError

# How long the paste chord gets to land before the clipboard is touched again.
_SETTLE_DELAY_SECONDS = 0.2


class ClipboardInserter(TextInserter):
    """Pastes the transcript through the clipboard, then puts the old text back."""

    def __init__(
        self,
        clipboard: Clipboard,
        chord: PasteChord,
        pause: Callable[[float], None] = sleep,
    ) -> None:
        self._clipboard = clipboard
        self._chord = chord
        self._pause = pause

    def insert_text(self, text: str) -> None:
        if not text:
            return
        previous_text: str | None = self._clipboard.read().text
        if self._paste(text):
            self._restore(previous_text, text)

    def _paste(self, text: str) -> bool:
        try:
            self._clipboard.write(text)
        except ClipboardError as exc:
            print(f"Clipboard insertion failed: {exc}", file=sys.stderr)
            return False
        try:
            self._chord.send()
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
