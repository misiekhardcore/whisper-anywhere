import json
import shutil
import sys

from .typers import ClipboardTyper, Typer, WtypeTyper, YdotoolTyper


class TextOutput:
    def __init__(self, stdout_mode: bool) -> None:
        self._stdout_mode = stdout_mode
        self._typer: Typer | None = None

    @staticmethod
    def _probe_typer() -> Typer | None:
        if shutil.which("wtype") and WtypeTyper._check_compositor():
            return WtypeTyper()
        if shutil.which("ydotool"):
            return YdotoolTyper()
        if shutil.which("wl-copy") and shutil.which("ydotool"):
            return ClipboardTyper()
        return None

    def _get_typer(self) -> Typer:
        if self._typer is None:
            self._typer = self._probe_typer()
            if self._typer is None:
                print(
                    "No typing tool found — ensure wl-clipboard and ydotool are installed.",
                    file=sys.stderr,
                )
                print("  bash install.sh", file=sys.stderr)
                sys.exit(1)
        return self._typer

    def emit(self, text: str | None) -> None:
        if not text:
            return
        if self._stdout_mode:
            print(json.dumps({"type": "final", "text": text}), flush=True)
            return
        self._get_typer().type_text(text)
