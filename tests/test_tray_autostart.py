"""Start at login: the two user units, driven through a fake systemctl."""

import subprocess
from typing import Sequence

from whisper_anywhere.tray.autostart import DAEMON_UNIT, TRAY_UNIT, LoginAutostart

SYSTEMCTL = "systemctl"
BOTH_UNITS = [DAEMON_UNIT, TRAY_UNIT]


class _FakeRunner:
    """Records every argv and answers with a scripted result."""

    def __init__(
        self,
        stdout: str = "",
        returncode: int = 0,
        error: OSError | None = None,
    ) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(list(argv), self.returncode, self.stdout, "")


class TestStartAtLoginActions:
    def test_checking_enables_both_units(self) -> None:
        runner = _FakeRunner()

        LoginAutostart(runner).set_enabled(True)

        assert runner.calls == [[SYSTEMCTL, "--user", "enable", DAEMON_UNIT, TRAY_UNIT]]

    def test_unchecking_disables_both_units(self) -> None:
        runner = _FakeRunner()

        LoginAutostart(runner).set_enabled(False)

        assert runner.calls == [
            [SYSTEMCTL, "--user", "disable", DAEMON_UNIT, TRAY_UNIT]
        ]


class TestStartAtLoginState:
    def test_both_units_enabled_reads_as_checked(self) -> None:
        runner = _FakeRunner(stdout="enabled\nenabled\n")

        assert LoginAutostart(runner).is_enabled() is True
        assert runner.calls == [
            [SYSTEMCTL, "--user", "is-enabled", DAEMON_UNIT, TRAY_UNIT]
        ]

    def test_one_disabled_unit_reads_as_unchecked(self) -> None:
        runner = _FakeRunner(stdout="enabled\ndisabled\n", returncode=1)

        assert LoginAutostart(runner).is_enabled() is False

    def test_no_state_output_is_unknown(self) -> None:
        runner = _FakeRunner(stdout="", returncode=1)

        assert LoginAutostart(runner).is_enabled() is None

    def test_a_missing_systemctl_is_unknown(self) -> None:
        runner = _FakeRunner(error=FileNotFoundError("systemctl"))

        assert LoginAutostart(runner).is_enabled() is None
