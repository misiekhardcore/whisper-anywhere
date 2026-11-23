import subprocess
import sys
from typing import Literal

from .base import TextInserter

TypingTool = Literal["ydotool", "wtype"]


class TypingInserter(TextInserter):
    """Fallback: injects the transcript one synthetic key event per character."""

    def __init__(self, tool: TypingTool) -> None:
        self._tool = tool

    def insert_text(self, text: str) -> bool:
        if not text:
            return False
        command: list[str] = (
            ["ydotool", "type", text] if self._tool == "ydotool" else ["wtype", text]
        )
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print(
                f"{self._tool} not found — install it: sudo apt install {self._tool}",
                file=sys.stderr,
            )
            return False
        if result.returncode != 0:
            if self._tool == "ydotool":
                print(
                    f"ydotool type failed (exit {result.returncode}) — "
                    "is ydotool.service running? "
                    "(systemctl --user status ydotool)",
                    file=sys.stderr,
                )
            else:
                print(
                    f"wtype failed (exit {result.returncode})",
                    file=sys.stderr,
                )
            return False
        return True
