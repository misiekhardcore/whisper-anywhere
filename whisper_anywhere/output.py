import asyncio
import json
import sys

from .insertion import TextInserter

_TRAILING_WHITESPACE = (" ", "\t", "\n")


def _spaced_for_pasting(text: str) -> str:
    """Separate this dictation from whatever the next one follows it with."""
    if text.endswith(_TRAILING_WHITESPACE):
        return text
    return f"{text} "


class TextOutput:
    def __init__(self, stdout_mode: bool, inserter: TextInserter | None = None) -> None:
        self._stdout_mode = stdout_mode
        self._inserter = inserter

    async def emit(self, text: str | None) -> None:
        """Deliver one finished transcript, off the event loop thread."""
        if not text:
            return
        if self._stdout_mode:
            print(json.dumps({"type": "final", "text": text}), flush=True)
            return
        assert self._inserter is not None, "insertion is resolved at startup"
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._inserter.insert_text, _spaced_for_pasting(text)
            )
        except Exception as exc:
            print(f"Insertion failed: {exc}", file=sys.stderr)
