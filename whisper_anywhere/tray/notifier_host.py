"""Registers the indicator with a StatusNotifier host that may arrive late."""

import sys
from typing import Callable

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
RETRY_DELAY_MS = 5000

RetryScheduler = Callable[[int, Callable[[], bool]], None]


class NotifierHost:
    """Keeps retrying registration instead of exiting when no host is running."""

    def __init__(
        self,
        register: Callable[[], None],
        host_present: Callable[[], bool],
        schedule_retry: RetryScheduler,
        retry_delay_ms: int = RETRY_DELAY_MS,
        warn: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
    ) -> None:
        self._register = register
        self._host_present = host_present
        self._schedule_retry = schedule_retry
        self._retry_delay_ms = retry_delay_ms
        self._warn = warn

    def start(self) -> None:
        """Register now when a host is there, otherwise say so once and retry."""
        if self._host_present():
            self._register()
            return
        self._warn(
            f"No {WATCHER_NAME} on the session bus; retrying until a "
            "status-notifier host registers."
        )
        self._schedule_retry(self._retry_delay_ms, self.retry)

    def retry(self) -> bool:
        """Register if a host appeared; keep the timer running while none has."""
        if not self._host_present():
            return True
        self._register()
        return False
