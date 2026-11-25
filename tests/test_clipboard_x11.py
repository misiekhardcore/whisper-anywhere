"""Live tests of the X11 clipboard backend against the real `xclip` binary.

The mocked tests in `test_insertion.py` pin command construction. These start a
throwaway Xvfb display and drive `xclip` itself, so the TARGETS output shape, the
exit codes and the real round-trip are checked against the tool rather than
against our assumptions about it. They skip on machines without `xclip` or Xvfb.
"""

import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from typing import Iterator

import pytest

from whisper_anywhere.insertion import ClipboardInserter, X11Clipboard
from whisper_anywhere.insertion.chord import PasteChord
from whisper_anywhere.insertion.focused_window import FocusedWindowQuery

pytestmark = pytest.mark.skipif(
    shutil.which("xclip") is None or shutil.which("Xvfb") is None,
    reason="needs xclip and Xvfb for the live X11 clipboard",
)

CLIPBOARD: list[str] = ["xclip", "-selection", "clipboard"]


class _RecordingChord(PasteChord):
    """Records the chords it is asked to send instead of injecting keystrokes."""

    TOOL = "ydotool"

    def __init__(self) -> None:
        self.terminal_flags: list[bool] = []

    def send(self, terminal: bool = False) -> None:
        self.terminal_flags.append(terminal)


class _NotATerminal(FocusedWindowQuery):
    def is_terminal(self) -> bool:
        return False


def _await_connections(display: str) -> None:
    deadline: float = time.monotonic() + 10
    while time.monotonic() < deadline:
        probe = subprocess.run(
            CLIPBOARD + ["-t", "TARGETS", "-o"],
            env={**os.environ, "DISPLAY": display},
            capture_output=True,
            text=True,
        )
        if "Can't open display" not in probe.stderr:
            return
        time.sleep(0.05)
    raise AssertionError(f"Xvfb on {display} never accepted connections")


@contextmanager
def _fresh_display() -> Iterator[str]:
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(
        [
            "Xvfb",
            "-displayfd",
            str(write_fd),
            "-screen",
            "0",
            "1024x768x24",
            "-nolisten",
            "tcp",
        ],
        pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(write_fd)
    previous_display: str | None = os.environ.get("DISPLAY")
    try:
        with os.fdopen(read_fd) as reported:
            number: str = reported.readline().strip()
        assert number, "Xvfb did not report a display"
        display: str = f":{number}"
        _await_connections(display)
        os.environ["DISPLAY"] = display
        yield display
    finally:
        if previous_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = previous_display
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture()
def x11_display() -> Iterator[str]:
    with _fresh_display() as display:
        yield display


def _targets(display: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        CLIPBOARD + ["-t", "TARGETS", "-o"],
        env={**os.environ, "DISPLAY": display},
        capture_output=True,
        text=True,
    )


def test_a_selection_nobody_owns_reads_as_no_text(x11_display: str) -> None:
    raw: subprocess.CompletedProcess = _targets(x11_display)

    assert raw.returncode != 0
    assert "not available" in raw.stderr
    assert X11Clipboard().read().text is None


def test_text_round_trips_through_the_real_binary(x11_display: str) -> None:
    X11Clipboard().write("zażółć gęślą jaźń")
    raw: subprocess.CompletedProcess = _targets(x11_display)

    assert raw.returncode == 0
    assert "UTF8_STRING" in raw.stdout.split()
    assert X11Clipboard().read().text == "zażółć gęślą jaźń"

    X11Clipboard().write("a")
    assert X11Clipboard().read().text == "a"

    X11Clipboard().write("")
    assert X11Clipboard().read().text == ""


def test_a_non_text_selection_reads_as_no_text(x11_display: str) -> None:
    subprocess.run(
        CLIPBOARD + ["-t", "image/png", "-i"],
        input=b"\x89PNG\r\n\x1a\nnot-really-a-png",
        check=True,
    )
    raw: subprocess.CompletedProcess = _targets(x11_display)

    assert "image/png" in raw.stdout.split()
    assert "UTF8_STRING" not in raw.stdout.split()
    assert X11Clipboard().read().text is None


def test_insertion_puts_the_previous_text_back(x11_display: str) -> None:
    clipboard = X11Clipboard()
    clipboard.write("previous text")
    chord = _RecordingChord()

    delivered: bool = ClipboardInserter(
        clipboard, chord, _NotATerminal(), pause=lambda _seconds: None
    ).insert_text("hello")

    assert delivered is True
    assert chord.terminal_flags == [False]
    assert clipboard.read().text == "previous text"


def test_a_clipboard_taken_during_the_settle_delay_is_not_overwritten(
    x11_display: str,
) -> None:
    clipboard = X11Clipboard()
    clipboard.write("previous")

    def rival_takes_the_clipboard(_delay: float) -> None:
        clipboard.write("rival text")

    ClipboardInserter(
        clipboard, _RecordingChord(), _NotATerminal(), pause=rival_takes_the_clipboard
    ).insert_text("hello")

    assert clipboard.read().text == "rival text"
