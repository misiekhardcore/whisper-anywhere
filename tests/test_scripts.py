"""Integration tests for install.sh and uninstall.sh.

Strategy: run the real scripts inside a temp HOME with stub executables on
PATH so no system-level side effects occur (no apt-get, no usermod, no
systemctl daemon changes, no pip network calls, no model downloads).  The
assertions focus on the file-system artefacts the scripts are responsible for:
config, both systemd units, the launcher, and their removal.
"""

import os
import pty
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Generator

import pytest

REPO_DIR: Path = Path(__file__).parent.parent
REAL_PYTHON: str = sys.executable


@pytest.fixture()
def fake_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Temporary HOME directory with no-op stubs for external commands."""
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()

    def stub(name: str, body: str) -> None:
        p: Path = bin_dir / name
        p.write_text(f"#!/usr/bin/env bash\n{body}\n")
        p.chmod(0o755)

    # Package manager — record the requested packages, install nothing
    stub("apt-get", 'echo "$*" >> "$APT_LOG"')

    # dpkg-query — reports nothing installed unless a test says otherwise, so
    # the package step is exercised instead of being skipped.
    stub(
        "dpkg-query",
        textwrap.dedent("""\
        if [[ "${DPKG_INSTALLED_ALL:-0}" == "1" ]]; then
            echo "install ok installed"
            exit 0
        fi
        exit 1
    """),
    )

    # systemctl — always succeed; record the calls, never touch the real daemon
    stub("systemctl", 'echo "$*" >> "$SYSTEMCTL_LOG"')

    # git — report this checkout as the only worktree, unless a test names more
    stub(
        "git",
        textwrap.dedent("""\
        if [[ "${1:-}" == "-C" ]]; then shift 2; fi
        if [[ "${1:-}" == "worktree" && "${2:-}" == "list" ]]; then
            printf 'worktree %s\\nHEAD deadbee\\nbranch refs/heads/main\\n\\n' \\
                "${WHISPER_PRIMARY:-$WHISPER_REPO_DIR}"
            if [[ -n "${WHISPER_LINKED:-}" ]]; then
                printf 'worktree %s\\nHEAD badc0de\\nbranch refs/heads/side\\n\\n' \\
                    "$WHISPER_LINKED"
            fi
            exit 0
        fi
        exit 1
    """),
    )

    # sudo — record the call, no-op for package/user management, pass the rest
    stub(
        "sudo",
        textwrap.dedent("""\
        echo "$*" >> "$SUDO_LOG"
        case "${1:-}" in
            usermod|gpasswd) exit 0 ;;
            *) exec "$@" ;;
        esac
    """),
    )

    # python3 — intercept pip calls and model loading; delegate everything
    # else to the real interpreter so evdev/sysconfig checks work normally
    stub(
        "python3",
        textwrap.dedent(f"""\
        if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "pip" ]]; then
            if [[ "${{REJECT_USER_PIP:-}}" == "1" &&
                  " $* " == *" --user "* &&
                  " $* " != *" --break-system-packages "* ]]; then
                exit 1
            fi
            echo "$*" >> "$PIP_LOG"
            exit 0
        fi
        if [[ "${{1:-}}" == "-c" ]] && echo "${{2:-}}" | grep -q "WhisperModel"; then
            exit 0
        fi
        if [[ "${{1:-}}" == "-c" ]] && echo "${{2:-}}" | grep -q "AutoModel"; then
            echo "$*" >> "$MODEL_LOG"
            exit 0
        fi
        if [[ "${{1:-}}" == "-c" ]] && echo "${{2:-}}" | grep -q "whisper_anywhere.__file__"; then
            if [[ -n "${{INSTALL_PROBE_EXIT:-}}" ]]; then exit "$INSTALL_PROBE_EXIT"; fi
            echo "${{INSTALL_PROBE_PATH:-$WHISPER_REPO_DIR}}"
            exit 0
        fi
        exec {REAL_PYTHON} "$@"
    """),
    )

    yield tmp_path


def _environment(
    home: Path,
    reject_user_pip: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    bin_dir: Path = home / "bin"
    return {
        **os.environ,
        "HOME": str(home),
        "USER": os.environ.get("USER", "testuser"),
        # Stubs come first so they shadow real system commands
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        # Force the scripts to use our python3 stub
        "PYTHON": str(bin_dir / "python3"),
        "PIP_LOG": str(home / "pip.log"),
        "APT_LOG": str(home / "apt.log"),
        "SYSTEMCTL_LOG": str(home / "systemctl.log"),
        "SUDO_LOG": str(home / "sudo.log"),
        "MODEL_LOG": str(home / "model.log"),
        # The git stub reports one worktree unless a test names a linked one.
        "WHISPER_REPO_DIR": str(REPO_DIR),
        "WHISPER_PRIMARY": "",
        "WHISPER_LINKED": "",
        "REJECT_USER_PIP": "1" if reject_user_pip else "0",
        "AUTOSTART": "",
        **(extra_env or {}),
    }


def _run(
    script: Path,
    home: Path,
    stdin: str | None = None,
    reject_user_pip: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        env=_environment(home, reject_user_pip, extra_env),
        capture_output=True,
        text=True,
        input=stdin,
    )


def _run_on_tty(
    script: Path,
    home: Path,
    answer: str,
) -> subprocess.CompletedProcess:
    master, slave = pty.openpty()
    process = subprocess.Popen(
        ["bash", str(script)],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(home),
        text=True,
    )
    os.close(slave)
    os.write(master, answer.encode())
    stdout, stderr = process.communicate(timeout=60)
    os.close(master)
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


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
        assert "vad" not in text.lower()

        service: Path = (
            fake_home / ".config" / "systemd" / "user" / "whisper-anywhere.service"
        )
        assert service.exists(), "service unit not created"
        unit: str = service.read_text()
        assert "ExecStart=" in unit
        assert "Restart=on-failure" in unit
        assert "WantedBy=default.target" in unit
        assert "After=ydotool.service" in unit

    def test_install_installs_cpu_pytorch(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert (
            "install --user torch torchaudio "
            "--index-url https://download.pytorch.org/whl/cpu"
        ) in pip_calls

    @pytest.mark.parametrize(
        ("default_version", "default_evdev_exit"),
        [("3.15.2", 0), ("3.14.4", 1)],
        ids=["newer-than-supported", "cannot-import-evdev"],
    )
    def test_install_selects_a_supported_python(
        self,
        fake_home: Path,
        default_version: str,
        default_evdev_exit: int,
    ) -> None:
        bin_dir: Path = fake_home / "bin"
        broken_body: str = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            if [[ "${1:-}" == "--version" ]]; then
                echo "Python __VERSION__"
                exit 0
            fi
            if [[ "${1:-}" == "-c" ]]; then
                case "${2:-}" in
                    *"import evdev"*) exit __EVDEV_EXIT__ ;;
                    *sysconfig*)
                        mkdir -p "$HOME/unsupported-purelib"
                        echo "$HOME/unsupported-purelib"
                        exit 0
                        ;;
                esac
                exit 0
            fi
            if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
                echo "$*" >> "$HOME/unsupported-pip.log"
                exit 1
            fi
            exit 0
        """
        )
        broken: Path = bin_dir / "python3"
        broken.write_text(
            broken_body.replace("__VERSION__", default_version).replace(
                "__EVDEV_EXIT__", str(default_evdev_exit)
            )
        )
        broken.chmod(0o755)

        supported: Path = bin_dir / "python3.14"
        supported.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                if [[ "${1:-}" == "--version" ]]; then
                    echo "Python 3.14.4"
                    exit 0
                fi
                if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
                    echo "$*" >> "$PIP_LOG"
                    exit 0
                fi
                if [[ "${1:-}" == "-c" ]] &&
                    echo "${2:-}" | grep -q "whisper_anywhere.__file__"; then
                    echo "$WHISPER_REPO_DIR"
                    exit 0
                fi
                exit 0
            """
            )
        )
        supported.chmod(0o755)

        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env={"PYTHON": ""}
        )
        assert result.returncode == 0, (
            f"install.sh exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        assert f"using {supported}" in result.stdout
        pip_calls: str = (fake_home / "pip.log").read_text()
        assert "install --user torch torchaudio" in pip_calls
        assert not (fake_home / "unsupported-pip.log").exists()

    def test_install_rejects_an_explicit_python_outside_the_supported_range(
        self, fake_home: Path
    ) -> None:
        unsupported: Path = fake_home / "bin" / "python3.15"
        unsupported.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                if [[ "${1:-}" == "--version" ]]; then
                    echo "Python 3.15.2"
                    exit 0
                fi
                if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
                    echo "$*" >> "$PIP_LOG"
                    exit 0
                fi
                exit 0
            """
            )
        )
        unsupported.chmod(0o755)

        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env={"PYTHON": str(unsupported)}
        )

        assert result.returncode != 0, "install.sh must refuse Python 3.15"
        assert f"PYTHON={unsupported}" in result.stdout
        assert "3.10-3.14" in result.stdout
        assert not (fake_home / "pip.log").exists()
        assert not (fake_home / ".config" / "whisper-anywhere").exists()

    def test_install_handles_externally_managed_python(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, reject_user_pip=True
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert "install --user --break-system-packages funasr" in pip_calls

    def test_install_adds_wl_clipboard_on_wayland(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh",
            fake_home,
            extra_env={"WAYLAND_DISPLAY": "wayland-0"},
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        packages: str = (fake_home / "apt.log").read_text()
        assert "wl-clipboard" in packages
        assert "ydotool" in packages

    def test_install_enables_autostart_by_default(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        calls: str = (fake_home / "systemctl.log").read_text()
        assert "enable whisper-anywhere.service whisper-anywhere-tray.service" in calls
        assert "restart whisper-anywhere.service whisper-anywhere-tray.service" in calls

    def test_install_honours_autostart_0_without_a_tty(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env={"AUTOSTART": "0"}
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        calls: str = (fake_home / "systemctl.log").read_text()
        assert "enable whisper-anywhere" not in calls
        assert "disable whisper-anywhere.service whisper-anywhere-tray.service" in calls

    def test_install_asks_one_question_on_a_tty_and_honours_no(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run_on_tty(
            REPO_DIR / "install.sh", fake_home, "n\n"
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        assert result.stderr.count("Start whisper-anywhere at login?") == 1
        calls: str = (fake_home / "systemctl.log").read_text()
        assert "enable whisper-anywhere" not in calls
        assert "disable whisper-anywhere.service whisper-anywhere-tray.service" in calls

    @pytest.mark.parametrize("answer", ["\n", "\x04"], ids=["enter", "eof"])
    def test_install_treats_an_empty_tty_answer_as_yes(
        self, fake_home: Path, answer: str
    ) -> None:
        result: subprocess.CompletedProcess = _run_on_tty(
            REPO_DIR / "install.sh", fake_home, answer
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        assert result.stderr.count("Start whisper-anywhere at login?") == 1
        calls: str = (fake_home / "systemctl.log").read_text()
        assert "enable whisper-anywhere.service whisper-anywhere-tray.service" in calls

    def test_install_writes_a_searchable_launcher_with_its_own_icon(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        launcher: Path = (
            fake_home / ".local" / "share" / "applications" / "whisper-anywhere.desktop"
        )
        assert launcher.exists(), "launcher entry not created"
        entry: str = launcher.read_text()
        assert (
            "Exec=systemctl --user start whisper-anywhere.service "
            "whisper-anywhere-tray.service"
        ) in entry
        assert "Icon=whisper-anywhere" in entry
        assert "Keywords=" in entry and "dictation" in entry
        assert "NoDisplay=true" not in entry and "Hidden=true" not in entry

        for size in (48, 64, 128, 256):
            icon: Path = (
                fake_home
                / ".local"
                / "share"
                / "icons"
                / "hicolor"
                / f"{size}x{size}"
                / "apps"
                / "whisper-anywhere.png"
            )
            assert icon.is_file(), f"launcher icon missing at {icon}"
            assert icon.stat().st_size > 0, f"launcher icon empty at {icon}"

    def test_install_writes_tray_unit_for_the_graphical_session(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        tray: Path = (
            fake_home / ".config" / "systemd" / "user" / "whisper-anywhere-tray.service"
        )
        assert tray.exists(), "tray unit not created"
        unit: str = tray.read_text()
        assert f"ExecStart={fake_home}/.local/bin/whisper-anywhere-tray" in unit
        assert "WantedBy=graphical-session.target" in unit
        assert "Restart=no" in unit

    def test_install_installs_gtk_and_appindicator_packages(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        packages: str = (fake_home / "apt.log").read_text()
        assert "python3-gi" in packages
        assert "gir1.2-ayatanaappindicator3-0.1" in packages
        assert "gir1.2-dbusmenu-glib-0.4" in packages

    def test_install_enables_ydotool_on_wayland(self, fake_home: Path) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh",
            fake_home,
            extra_env={"WAYLAND_DISPLAY": "wayland-0"},
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        assert "ydotool" in result.stdout
        assert "Insertion: transcript written to the clipboard" in result.stdout

    def test_install_removes_legacy_desktop_entry(self, fake_home: Path) -> None:
        autostart: Path = fake_home / ".config" / "autostart"
        autostart.mkdir(parents=True)
        desktop: Path = autostart / "whisper-anywhere.desktop"
        desktop.write_text("[Desktop Entry]\nExec=whisper-anywhere\n")

        _run(REPO_DIR / "install.sh", fake_home)

        assert not desktop.exists(), "legacy .desktop entry should be removed"

    def test_install_reports_the_hotkey_from_an_existing_config(
        self, fake_home: Path
    ) -> None:
        _write_config(fake_home, "hotkey=KEY_F12\nengine=faster-whisper\n")

        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        assert "Hotkey: KEY_F12" in result.stdout
        assert "Hotkey: Ctrl+Super+Space" not in result.stdout

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

    def test_uninstall_removes_launcher_tray_unit_and_socket(
        self, fake_home: Path
    ) -> None:
        runtime_dir: Path = fake_home / "run" / "whisper-anywhere"
        runtime_dir.mkdir(parents=True)
        socket: Path = runtime_dir / "state.sock"
        socket.touch()
        env: dict[str, str] = {"XDG_RUNTIME_DIR": str(fake_home / "run")}

        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env=env
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"

        result = _run(REPO_DIR / "uninstall.sh", fake_home, stdin="n\n", extra_env=env)
        assert result.returncode == 0, f"uninstall.sh failed:\n{result.stderr}"

        service_dir: Path = fake_home / ".config" / "systemd" / "user"
        launcher: Path = (
            fake_home / ".local" / "share" / "applications" / "whisper-anywhere.desktop"
        )
        assert not launcher.exists(), "launcher entry should be removed"
        assert not (service_dir / "whisper-anywhere.service").exists()
        assert not (service_dir / "whisper-anywhere-tray.service").exists()
        assert not socket.exists(), "status socket should be removed"
        assert not (
            fake_home
            / ".local"
            / "share"
            / "icons"
            / "hicolor"
            / "256x256"
            / "apps"
            / "whisper-anywhere.png"
        ).exists(), "launcher icon should be removed"

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


def _write_config(home: Path, body: str) -> None:
    """Give the installer a pre-existing config, the way a second run finds one."""
    config_dir: Path = home / ".config" / "whisper-anywhere"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(body)


class TestInstallRobustness:
    """The four ways an install can look fine and still leave the machine broken."""

    def test_install_targets_the_primary_worktree(self, fake_home: Path) -> None:
        """An editable install must not point into a worktree that can be removed."""
        primary: Path = fake_home / "primary"
        linked: Path = fake_home / "linked"
        primary.mkdir()
        linked.mkdir()

        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh",
            fake_home,
            extra_env={
                "WHISPER_PRIMARY": str(primary),
                "WHISPER_LINKED": str(linked),
                "INSTALL_PROBE_PATH": str(primary),
            },
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert f"-e {primary}" in pip_calls
        assert f"-e {linked}" not in pip_calls
        assert "primary worktree" in result.stdout

    def test_install_falls_back_when_git_cannot_list_worktrees(
        self, fake_home: Path
    ) -> None:
        git: Path = fake_home / "bin" / "git"
        git.write_text("#!/usr/bin/env bash\nexit 1\n")
        git.chmod(0o755)

        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        assert f"-e {REPO_DIR}" in (fake_home / "pip.log").read_text()

    def test_install_fails_when_the_installed_package_resolves_elsewhere(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh",
            fake_home,
            extra_env={"INSTALL_PROBE_PATH": "/gone/worktree"},
        )

        assert result.returncode != 0, "install.sh must fail on a misdirected install"
        assert "/gone/worktree" in result.stdout
        assert str(REPO_DIR) in result.stdout

    def test_install_fails_when_the_installed_package_cannot_be_imported(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh",
            fake_home,
            extra_env={"INSTALL_PROBE_EXIT": "1"},
        )

        assert result.returncode != 0, "install.sh must fail when nothing imports"
        assert "not importable" in result.stdout

    def test_install_skips_apt_when_every_package_is_present(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env={"DPKG_INSTALLED_ALL": "1"}
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        assert not (fake_home / "apt.log").exists(), "apt must not run needlessly"
        sudo_log: Path = fake_home / "sudo.log"
        if sudo_log.exists():
            assert "apt-get" not in sudo_log.read_text()
        assert "already installed" in result.stdout

    def test_install_installs_only_the_configured_engine(self, fake_home: Path) -> None:
        _write_config(fake_home, "engine=faster-whisper\nmodel=distil-medium.en\n")

        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert "faster-whisper av<19" in pip_calls
        assert "torch" not in pip_calls, "the SenseVoice stack is not needed here"
        assert "funasr" not in pip_calls

    def test_install_installs_the_sensevoice_stack_by_default(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert "install --user torch torchaudio" in pip_calls
        assert "funasr" in pip_calls
        assert "faster-whisper" not in pip_calls

    def test_install_honours_an_engine_override(self, fake_home: Path) -> None:
        _write_config(fake_home, "engine=sensevoice\n")

        result: subprocess.CompletedProcess = _run(
            REPO_DIR / "install.sh", fake_home, extra_env={"ENGINE": "vosk"}
        )
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        pip_calls: str = (fake_home / "pip.log").read_text()
        assert "install --user vosk" in pip_calls
        assert "torch" not in pip_calls

    def test_install_skips_the_sensevoice_model_preload_for_another_engine(
        self, fake_home: Path
    ) -> None:
        _write_config(fake_home, "engine=faster-whisper\n")

        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        assert not (fake_home / "model.log").exists(), "no SenseVoice download expected"
        assert "skipping" in result.stdout

    def test_install_preloads_the_model_for_the_sensevoice_engine(
        self, fake_home: Path
    ) -> None:
        result: subprocess.CompletedProcess = _run(REPO_DIR / "install.sh", fake_home)
        assert result.returncode == 0, f"install.sh failed:\n{result.stdout}"

        assert (fake_home / "model.log").exists()
