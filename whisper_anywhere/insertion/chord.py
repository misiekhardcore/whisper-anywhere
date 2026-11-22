import subprocess
from abc import ABC, abstractmethod

CTRL_V_KEYCODES: tuple[int, int] = (29, 47)


class ChordError(Exception):
    """The chord injector is missing or refused the chord."""


class PasteChord(ABC):
    """Sends the ordinary paste chord, Ctrl+V, as a single chord."""

    TOOL: str

    @abstractmethod
    def send(self) -> None:
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

    def send(self) -> None:
        ctrl, v = CTRL_V_KEYCODES
        self._run(["ydotool", "key", f"{ctrl}:1", f"{v}:1", f"{v}:0", f"{ctrl}:0"])

    def _failure_message(self, returncode: int) -> str:
        return (
            f"ydotool key failed (exit {returncode}) — "
            "is ydotool.service running? (systemctl --user status ydotool)"
        )


class WtypeChord(PasteChord):
    TOOL = "wtype"

    def send(self) -> None:
        self._run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])
