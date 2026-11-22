import sys

from .base import TextInserter
from .chord import ChordError, PasteChord
from .clipboard import Clipboard, ClipboardError


class ClipboardInserter(TextInserter):
    """Writes the transcript to the clipboard and sends one paste chord."""

    def __init__(self, clipboard: Clipboard, chord: PasteChord) -> None:
        self._clipboard = clipboard
        self._chord = chord

    def insert_text(self, text: str) -> None:
        if not text:
            return
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
