import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import monotonic
from typing import Callable

# The whole query is bounded by this, across both probes, so a compositor that
# does not answer quickly can never hold up insertion for long.
QUERY_TIMEOUT_SECONDS = 0.5

# Window classes of terminal emulators, matched case-insensitively against the
# focused window's class and title.
TERMINAL_NAMES = frozenset(
    {
        "alacritty",
        "com.mitchellh.ghostty",
        "foot",
        "ghostty",
        "gnome-terminal",
        "gnome-terminal-server",
        "hyper",
        "kgx",
        "kitty",
        "konsole",
        "lxterminal",
        "org.gnome.console",
        "org.gnome.terminal",
        "org.wezfurlong.wezterm",
        "qterminal",
        "rxvt",
        "sakura",
        "st",
        "tabby",
        "terminal",
        "terminator",
        "terminology",
        "termite",
        "tilix",
        "urxvt",
        "uxterm",
        "wezterm",
        "xfce4-terminal",
        "xterm",
    }
)


class FocusedWindowQuery(ABC):
    """Answers whether the focused window is a terminal emulator."""

    @abstractmethod
    def is_terminal(self) -> bool:
        """True only for a recognisable terminal; unknown answers read as False."""


@dataclass(frozen=True)
class WindowIdentity:
    window_class: str | None
    title: str | None


def is_terminal_window(identity: WindowIdentity) -> bool:
    for name in (identity.window_class, identity.title):
        if name and name.strip().lower() in TERMINAL_NAMES:
            return True
    return False


def _identity(window_class: object, title: object) -> WindowIdentity | None:
    """Both fields are optional; an answer with neither is not an answer."""
    if not isinstance(window_class, str) and not isinstance(title, str):
        return None
    return WindowIdentity(
        window_class if isinstance(window_class, str) else None,
        title if isinstance(title, str) else None,
    )


@dataclass(frozen=True)
class _Probe:
    command: tuple[str, ...]
    parse: Callable[[str], WindowIdentity | None]


def _parse_hyprctl(output: str) -> WindowIdentity | None:
    answer = json.loads(output)
    if not isinstance(answer, dict):
        return None
    return _identity(answer.get("class"), answer.get("title"))


def _focused_sway_node(node: object) -> dict | None:
    if not isinstance(node, dict):
        return None
    if node.get("focused") is True:
        return node
    children = list(node.get("nodes") or []) + list(node.get("floating_nodes") or [])
    for child in children:
        focused = _focused_sway_node(child)
        if focused is not None:
            return focused
    return None


def _parse_swaymsg(output: str) -> WindowIdentity | None:
    focused = _focused_sway_node(json.loads(output))
    if focused is None:
        return None
    properties = focused.get("window_properties")
    if not isinstance(properties, dict):
        properties = {}
    return _identity(
        focused.get("app_id") or properties.get("class"), focused.get("name")
    )


_PROBES: tuple[_Probe, ...] = (
    _Probe(("hyprctl", "activewindow", "-j"), _parse_hyprctl),
    _Probe(("swaymsg", "-t", "get_tree"), _parse_swaymsg),
)


class CompositorWindowQuery(FocusedWindowQuery):
    """Asks `hyprctl`, then `swaymsg`, what the focused window is."""

    def is_terminal(self) -> bool:
        deadline = monotonic() + QUERY_TIMEOUT_SECONDS
        for probe in _PROBES:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            identity = self._ask(probe, remaining)
            if identity is not None:
                return is_terminal_window(identity)
        return False

    @staticmethod
    def _ask(probe: _Probe, timeout: float) -> WindowIdentity | None:
        try:
            result = subprocess.run(
                list(probe.command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            return probe.parse(result.stdout)
        except (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValueError):
            return None
