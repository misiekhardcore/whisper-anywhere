"""Start at login: the two user units, driven through an injectable runner."""

import subprocess
from typing import Protocol, Sequence

DAEMON_UNIT = "whisper-anywhere.service"
TRAY_UNIT = "whisper-anywhere-tray.service"


class CommandRunner(Protocol):
    """Runs one systemctl command and returns its completed result."""

    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(list(argv), capture_output=True, text=True)


class LoginAutostart:
    """Whether the daemon and the tray start at login, and how to change it."""

    def __init__(
        self,
        runner: CommandRunner,
        units: Sequence[str] = (DAEMON_UNIT, TRAY_UNIT),
    ) -> None:
        self._runner = runner
        self._units = list(units)

    def is_enabled(self) -> bool | None:
        """Checked only when systemd names a state for both units."""
        try:
            result = self._runner.run(
                ["systemctl", "--user", "is-enabled", *self._units]
            )
        except OSError:
            return None
        states = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(states) != len(self._units):
            return None
        return all(state == "enabled" for state in states)

    def set_enabled(self, enabled: bool) -> None:
        action = "enable" if enabled else "disable"
        self._runner.run(["systemctl", "--user", action, *self._units])
