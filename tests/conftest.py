"""Shared e2e fixtures.

``installed_app`` optionally runs the real ``install.sh`` before the end-to-end
tests and ``uninstall.sh`` after them, so the e2e exercises the actual install
flow. It is active only when ``WHISPER_E2E_INSTALL=1`` and skips (rather than
fails) when the scripts can't complete in the current environment — honouring
the "install if possible" intent. When the flag is unset it yields ``None`` so
the in-process e2e still runs unchanged.
"""

import os
import subprocess
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home()
BIN = HOME / ".local/bin/whisper-anywhere"
SERVICE_UNIT = HOME / ".config/systemd/user/whisper-anywhere.service"
CONFIG = HOME / ".config/whisper-anywhere/config"


@pytest.fixture(scope="session")
def installed_app():
    if not os.environ.get("WHISPER_E2E_INSTALL"):
        yield None
        return

    res = subprocess.run(
        ["bash", "install.sh"], cwd=REPO, text=True, capture_output=True
    )
    if res.returncode != 0:
        pytest.skip(
            "install.sh could not complete in this environment:\n"
            + (res.stdout[-1500:] + "\n" + res.stderr[-1500:])
        )

    assert BIN.exists(), "install.sh did not create ~/.local/bin/whisper-anywhere"
    assert SERVICE_UNIT.exists(), "install.sh did not create the systemd user unit"

    try:
        yield types.SimpleNamespace(
            repo=REPO, bin=BIN, unit=SERVICE_UNIT, config=CONFIG
        )
    finally:
        # 'n' answers uninstall.sh's interactive "remove config?" prompt.
        subprocess.run(
            ["bash", "uninstall.sh"],
            cwd=REPO,
            input="n\n",
            text=True,
            capture_output=True,
        )
        assert not SERVICE_UNIT.exists(), "uninstall.sh left the systemd unit behind"
