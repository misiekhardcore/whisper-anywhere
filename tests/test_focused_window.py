import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.insertion.focused_window import (
    QUERY_TIMEOUT_SECONDS,
    CompositorWindowQuery,
)

HYPRCTL_COMMAND: list[str] = ["hyprctl", "activewindow", "-j"]
SWAYMSG_COMMAND: list[str] = ["swaymsg", "-t", "get_tree"]


def _hyprctl_answer(window_class: str, title: str = "") -> str:
    return json.dumps({"class": window_class, "title": title})


def _sway_answer(focused_class: str, focused_title: str = "shell") -> str:
    return json.dumps(
        {
            "name": "root",
            "focused": False,
            "nodes": [
                {
                    "name": "workspace",
                    "focused": False,
                    "nodes": [
                        {
                            "name": focused_title,
                            "app_id": focused_class,
                            "focused": True,
                            "nodes": [],
                        }
                    ],
                },
            ],
        }
    )


class TestCompositorWindowQuery:
    def test_a_terminal_class_in_the_focused_window_is_a_terminal(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout=_hyprctl_answer("kitty"))

            assert CompositorWindowQuery().is_terminal() is True

        assert run.call_args.args[0] == HYPRCTL_COMMAND

    def test_a_non_terminal_window_is_not_a_terminal(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(
                returncode=0, stdout=_hyprctl_answer("firefox", "Mozilla Firefox")
            )

            assert CompositorWindowQuery().is_terminal() is False

        assert [call.args[0] for call in run.call_args_list] == [HYPRCTL_COMMAND]

    def test_swaymsg_answers_when_hyprctl_is_missing(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                FileNotFoundError,
                MagicMock(returncode=0, stdout=_sway_answer("foot")),
            ]

            assert CompositorWindowQuery().is_terminal() is True

        assert [call.args[0] for call in run.call_args_list] == [
            HYPRCTL_COMMAND,
            SWAYMSG_COMMAND,
        ]

    def test_swaymsg_answers_when_hyprctl_fails(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                MagicMock(returncode=1, stdout=""),
                MagicMock(returncode=0, stdout=_sway_answer("firefox")),
            ]

            assert CompositorWindowQuery().is_terminal() is False

        assert run.call_args_list[-1].args[0] == SWAYMSG_COMMAND

    def test_the_focused_sway_node_is_the_one_read(self) -> None:
        with patch("subprocess.run") as run:
            run.side_effect = [
                FileNotFoundError,
                MagicMock(returncode=0, stdout=_sway_answer("kitty", "~/Projects")),
            ]

            assert CompositorWindowQuery().is_terminal() is True

    def test_a_terminal_title_alone_is_recognised(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(
                returncode=0, stdout=_hyprctl_answer("", "Terminal")
            )

            assert CompositorWindowQuery().is_terminal() is True

    def test_no_compositor_query_is_unknown_without_an_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert CompositorWindowQuery().is_terminal() is False

        assert capsys.readouterr().err == ""

    def test_a_timed_out_query_is_unknown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("hyprctl", QUERY_TIMEOUT_SECONDS),
        ):
            assert CompositorWindowQuery().is_terminal() is False

        assert capsys.readouterr().err == ""

    def test_the_whole_query_is_bounded_by_one_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for tool in ("hyprctl", "swaymsg"):
            script: Path = tmp_path / tool
            script.write_text("#!/usr/bin/env bash\nsleep 5\n")
            script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

        started: float = time.monotonic()
        assert CompositorWindowQuery().is_terminal() is False
        elapsed: float = time.monotonic() - started

        assert elapsed < QUERY_TIMEOUT_SECONDS + 0.4, "a hanging compositor stalled"

    def test_an_unparseable_answer_is_unknown(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="not json at all")

            assert CompositorWindowQuery().is_terminal() is False

    def test_a_non_object_answer_is_unknown(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="[1, 2, 3]")

            assert CompositorWindowQuery().is_terminal() is False

    def test_the_query_is_bounded_and_detached_from_our_streams(self) -> None:
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout=_hyprctl_answer("kitty"))

            CompositorWindowQuery().is_terminal()

        kwargs = run.call_args.kwargs
        assert 0 < kwargs["timeout"] <= QUERY_TIMEOUT_SECONDS
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
