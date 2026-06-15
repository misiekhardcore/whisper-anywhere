import subprocess
import sys

from .base import Typer


class ClipboardTyper(Typer):
    _KEY_LEFTCTRL = 29
    _KEY_V = 47
    _KEY_BACKSPACE = 14

    @staticmethod
    def _save_clipboard() -> str | None:
        try:
            r = subprocess.run(["wl-paste"], capture_output=True, text=True, timeout=2)
            return r.stdout if r.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _copy(text: str) -> None:
        try:
            subprocess.run(["wl-copy", text])
        except FileNotFoundError:
            print(
                "wl-copy not found — install it: sudo apt install wl-clipboard",
                file=sys.stderr,
            )

    @staticmethod
    def _paste() -> None:
        try:
            subprocess.run(
                [
                    "ydotool",
                    "key",
                    f"{ClipboardTyper._KEY_LEFTCTRL}:1",
                    f"{ClipboardTyper._KEY_V}:1",
                    f"{ClipboardTyper._KEY_V}:0",
                    f"{ClipboardTyper._KEY_LEFTCTRL}:0",
                ]
            )
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )

    def type_text(self, text: str) -> None:
        if not text:
            return
        saved = self._save_clipboard()
        self._copy(text)
        self._paste()
        if saved is not None:
            self._copy(saved)

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        try:
            subprocess.run(
                ["ydotool", "key"]
                + [f"{self._KEY_BACKSPACE}:1", f"{self._KEY_BACKSPACE}:0"] * n
            )
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )
