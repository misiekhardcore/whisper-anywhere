import json
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod


class Typer(ABC):
    @abstractmethod
    def type_text(self, text: str) -> None:
        ...

    @abstractmethod
    def backspace(self, n: int) -> None:
        ...


class WtypeTyper(Typer):
    def type_text(self, text: str) -> None:
        if not text:
            return
        try:
            result = subprocess.run(["wtype", text])
        except FileNotFoundError:
            print(
                "wtype not found — install it: sudo apt install wtype",
                file=sys.stderr,
            )
            return
        if result.returncode != 0:
            print(f"wtype failed (exit {result.returncode})", file=sys.stderr)

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        try:
            subprocess.run(["wtype"] + ["-k", "BackSpace"] * n)
        except FileNotFoundError:
            print(
                "wtype not found — install it: sudo apt install wtype",
                file=sys.stderr,
            )


class YdotoolTyper(Typer):
    _KEY_BACKSPACE = 14

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

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        keys = [f"{self._KEY_BACKSPACE}:1", f"{self._KEY_BACKSPACE}:0"] * n
        try:
            subprocess.run(["ydotool", "key"] + keys)
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )


class TextOutput:
    def __init__(self, stdout_mode: bool) -> None:
        self._stdout_mode = stdout_mode
        self._typer: Typer | None = None

    @staticmethod
    def _probe_typer() -> Typer | None:
        if shutil.which("wtype"):
            return WtypeTyper()
        if shutil.which("ydotool"):
            return YdotoolTyper()
        return None

    def _get_typer(self) -> Typer:
        if self._typer is None:
            self._typer = self._probe_typer()
            if self._typer is None:
                print(
                    "No typing tool found — install wtype (Wayland) or ydotool (X11).",
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
