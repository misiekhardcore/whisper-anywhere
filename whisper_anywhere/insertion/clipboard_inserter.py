import sys
from time import sleep

from .base import TextInserter
from .chord import ChordError, PasteChord
from .clipboard import Clipboard, ClipboardError

# How long the paste chord gets to land before the clipboard is touched again.
SETTLE_DELAY_SECONDS = 0.2


class ClipboardInserter(TextInserter):
    """Pastes the transcript through the clipboard, then puts the old text back."""

    def __init__(self, clipboard: Clipboard, chord: PasteChord) -> None:
        self._clipboard = clipboard
        self._chord = chord

    def insert_text(self, text: str) -> None:
        if not text:
            return
        previous_text: str | None = self._clipboard.read().text
        try:
            self._clipboard.write(text)
        except ClipboardError as exc:
            print(f"Clipboard insertion failed: {exc}", file=sys.stderr)
            return
        try:
            self._chord.send()
        except ChordError as exc:
            print(
                f"Paste chord failed: {exc} — transcript left on the clipboard",
                file=sys.stderr,
            )
            return
        if previous_text is None:
            return
        sleep(SETTLE_DELAY_SECONDS)
        if self._clipboard.read().text != text:
            return
        try:
            self._clipboard.write(previous_text)
        except ClipboardError as exc:
            print(
                f"Clipboard restore failed: {exc} — transcript left on the clipboard",
                file=sys.stderr,
            )
