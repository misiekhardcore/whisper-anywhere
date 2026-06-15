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
        if shutil.which("wl-copy") and shutil.which("ydotool"):
            return ClipboardTyper()
        if shutil.which("ydotool"):
            return YdotoolTyper()
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
            print(json.dumps({"text": text}), flush=True)
            return
        self._get_typer().type_text(text)

    def emit_partial(self, prev_text: str, new_text: str) -> None:
        if prev_text == new_text:
            return
        if self._stdout_mode:
            print(json.dumps({"type": "partial", "text": new_text}), flush=True)
            return
        prefix_len = self._common_prefix_len(prev_text, new_text)
        del_len = len(prev_text) - prefix_len
        suffix = new_text[prefix_len:]
        self._get_typer().backspace(del_len)
        if suffix:
            self._get_typer().type_text(suffix)

    def emit_final(self, prev_text: str, final_text: str) -> None:
        if self._stdout_mode:
            if final_text:
                print(json.dumps({"type": "final", "text": final_text}), flush=True)
            return
        if prev_text == final_text:
            return
        prefix_len = self._common_prefix_len(prev_text, final_text)
        del_len = len(prev_text) - prefix_len
        suffix = final_text[prefix_len:]
        self._get_typer().backspace(del_len)
        if suffix:
            self._get_typer().type_text(suffix)

    @staticmethod
    def _common_prefix_len(a: str, b: str) -> int:
        n = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                break
            n += 1
        return n
