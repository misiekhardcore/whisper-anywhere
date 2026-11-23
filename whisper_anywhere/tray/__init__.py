"""The tray view of the daemon: one separate process, never GTK inside the daemon."""

from .appearance import Appearance, appearance_for
from .controller import TrayController
from .presenter import TrayPresenter

__all__ = ["Appearance", "TrayController", "TrayPresenter", "appearance_for"]
