"""Integration tests for install.sh and uninstall.sh.

Strategy: run the real scripts inside a temp HOME with stub executables on
PATH so no system-level side effects occur (no apt-get, no usermod, no
systemctl daemon changes, no pip network calls, no model downloads).  The
assertions focus on the file-system artefacts the scripts are responsible for:
config file, systemd service unit, and legacy .desktop migration.
"""

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Generator

import pytest

REPO_DIR: Path = Path(__file__).parent.parent
REAL_PYTHON: str = subprocess.check_output(["which", "python3"], text=True).strip()


@pytest.fixture()
def fake_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Temporary HOME directory with no-op stubs for external commands."""
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()

    def stub(name: str, body: str) -> None:
        p: Path = bin_dir / name
        p.write_text(f"#!/usr/bin/env bash\n{body}\n")
        p.chmod(0o755)

    # Package manager — do nothing
    stub("apt-get", "exit 0")

    # systemctl — always succeed; never touches the real daemon
    stub("systemctl", "exit 0")

    # sudo — no-op for package/user management, pass through everything else
    stub(
        "sudo",
        textwrap.dedent("""\
        case "${1:-}" in
            apt-get|usermod|gpasswd) exit 0 ;;
            *) exec "$@" ;;
        esac
    """),
    )

    # python3 — intercept pip calls and model loading; delegate everything
    # else to the real interpreter so evdev/sysconfig checks work normally
    stub(
        "python3",
        textwrap.dedent(f"""\
        if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "pip" ]]; then exit 0; fi
        if [[ "${{1:-}}" == "-c" ]] && echo "${{2:-}}" | grep -q "WhisperModel"; then
            exit 0
        fi
        exec {REAL_PYTHON} "$@"
    """),
    )

    yield tmp_path


def _run(
    script: Path, home: Path, stdin: str | None = None
) -> subprocess.CompletedProcess:
    bin_dir: Path = home / "bin"
    env: dict[str, str] = {
        **os.environ,
        "HOME": str(home),
        "USER": os.environ.get("USER", "testuser"),
        # Stubs come first so they shadow real system commands
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        # Force the scripts to use our python3 stub
        "PYTHON": str(bin_dir / "python3"),
    }
    return subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        input=stdin,
    )


class TestInstallUninstall:
    def test_install_creates_config_and_service(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, (
            f"install.sh exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        config: Path = fake_home / ".config" / "whisper-anywhere" / "config"
        assert config.exists(), "config file not created"
        text: str = config.read_text()
        assert "hotkey" in text
        assert "model" in text
        assert "language" in text

        service: Path = (
            fake_home / ".config" / "systemd" / "user" / "whisper-anywhere.service"
        )
        assert service.exists(), "service unit not created"
        unit: str = service.read_text()
        assert "ExecStart=" in unit
        assert "Restart=on-failure" in unit
        assert "WantedBy=default.target" in unit
        assert "After=ydotool.service" in unit

    def test_install_removes_legacy_desktop_entry(self, fake_home: Path) -> None:
        autostart: Path = fake_home / ".config" / "autostart"
        autostart.mkdir(parents=True)
        desktop: Path = autostart / "whisper-anywhere.desktop"
        desktop.write_text("[Desktop Entry]\nExec=whisper-anywhere\n")

        _run(REPO_DIR / "install.sh", fake_home)

        assert not desktop.exists(), "legacy .desktop entry should be removed"

    def test_install_does_not_overwrite_existing_config(self, fake_home: Path) -> None:
        config_dir: Path = fake_home / ".config" / "whisper-anywhere"
        config_dir.mkdir(parents=True)
        existing: Path = config_dir / "config"
        existing.write_text("hotkey=KEY_F12\n")

        _run(REPO_DIR / "install.sh", fake_home)

        assert existing.read_text() == "hotkey=KEY_F12\n", (
            "existing config must not be overwritten"
        )

    def test_uninstall_removes_service_and_config(self, fake_home: Path) -> None:
        # Install first so there is something to remove
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        service: Path = (
            fake_home / ".config" / "systemd" / "user" / "whisper-anywhere.service"
        )
        config_dir: Path = fake_home / ".config" / "whisper-anywhere"
        assert service.exists()
        assert config_dir.exists()

        # Answer 'y' to the "remove config?" prompt
        result = _run(REPO_DIR / "uninstall.sh", fake_home, stdin="y\n")
        assert result.returncode == 0, f"uninstall.sh failed:\n{result.stderr}"

        assert not service.exists(), "service unit should be removed"
        assert not config_dir.exists(), (
            "config dir should be removed when user answers y"
        )

    def test_uninstall_keeps_config_when_declined(self, fake_home: Path) -> None:
        _run(REPO_DIR / "install.sh", fake_home)

        config_dir: Path = fake_home / ".config" / "whisper-anywhere"
        assert config_dir.exists()

        # Answer 'n' to the "remove config?" prompt
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "uninstall.sh", fake_home, stdin="n\n"
        )
        assert result.returncode == 0, f"uninstall.sh failed:\n{result.stderr}"

        assert config_dir.exists(), "config dir should be kept when user answers n"
