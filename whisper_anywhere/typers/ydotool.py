import subprocess
import sys

from .base import Typer


class YdotoolTyper(Typer):
    def type_text(self, text: str) -> None:
        if not text:
            return
        try:
            result = subprocess.run(["ydotool", "type", text])
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )
            return
        if result.returncode != 0:
            print(
                f"ydotool type failed (exit {result.returncode}) — "
                "is ydotool.service running? (systemctl --user status ydotool)",
                file=sys.stderr,
            )
