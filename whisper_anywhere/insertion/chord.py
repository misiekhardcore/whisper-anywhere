import subprocess
from abc import ABC, abstractmethod

CTRL_KEYCODE = 29
SHIFT_KEYCODE = 42
V_KEYCODE = 47


class ChordError(Exception):
    """The chord injector is missing or refused the chord."""


class PasteChord(ABC):
    """Sends the paste chord as a single chord: Ctrl+V, or Ctrl+Shift+V in a terminal."""

    TOOL: str

    @abstractmethod
    def send(self, terminal: bool = False) -> None:
        """Send the chord; raises ``ChordError``."""

    def _run(self, command: list[str]) -> None:
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ChordError(
                f"{self.TOOL} not found — install it: sudo apt install {self.TOOL}"
            ) from exc
        if result.returncode != 0:
            raise ChordError(self._failure_message(result.returncode))

    def _failure_message(self, returncode: int) -> str:
        return f"{self.TOOL} failed (exit {returncode})"


class YdotoolChord(PasteChord):
    TOOL = "ydotool"

    def send(self, terminal: bool = False) -> None:
        if terminal:
            sequence = [CTRL_KEYCODE, SHIFT_KEYCODE, V_KEYCODE]
        else:
            sequence = [CTRL_KEYCODE, V_KEYCODE]
        pressed = [f"{key}:1" for key in sequence]
        released = [f"{key}:0" for key in reversed(sequence)]
        self._run(["ydotool", "key", *pressed, *released])

    def _failure_message(self, returncode: int) -> str:
        return (
            f"ydotool key failed (exit {returncode}) — "
            "is ydotool.service running? (systemctl --user status ydotool)"
        )


class WtypeChord(PasteChord):
    TOOL = "wtype"

    def send(self, terminal: bool = False) -> None:
        if terminal:
            command = [
                "wtype",
                "-M",
                "ctrl",
                "-M",
                "shift",
                "-k",
                "v",
                "-m",
                "shift",
                "-m",
                "ctrl",
            ]
        else:
            command = ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]
        self._run(command)
