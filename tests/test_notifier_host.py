from typing import Callable

from whisper_anywhere.tray.notifier_host import WATCHER_NAME, NotifierHost


class _SessionBus:
    """A host that appears only once the test lets it."""

    def __init__(self, present: bool = False) -> None:
        self.present = present


class _RetryTimer:
    def __init__(self) -> None:
        self.delay_ms: int | None = None
        self.callback: Callable[[], bool] | None = None

    def __call__(self, delay_ms: int, callback: Callable[[], bool]) -> None:
        self.delay_ms = delay_ms
        self.callback = callback

    def fire(self) -> bool:
        assert self.callback is not None
        return self.callback()


class _Registration:
    def __init__(self) -> None:
        self.count: int = 0

    def __call__(self) -> None:
        self.count += 1


class TestNotifierHost:
    def test_a_present_host_registers_immediately_without_a_warning(self) -> None:
        bus = _SessionBus(present=True)
        register = _Registration()
        warnings: list[str] = []

        NotifierHost(
            register=register,
            host_present=lambda: bus.present,
            schedule_retry=_RetryTimer(),
            warn=warnings.append,
        ).start()

        assert register.count == 1
        assert warnings == []

    def test_a_missing_host_is_named_once_and_retried_until_it_registers(
        self,
    ) -> None:
        bus = _SessionBus(present=False)
        register = _Registration()
        timer = _RetryTimer()
        warnings: list[str] = []

        NotifierHost(
            register=register,
            host_present=lambda: bus.present,
            schedule_retry=timer,
            warn=warnings.append,
        ).start()

        assert register.count == 0
        assert len(warnings) == 1
        assert WATCHER_NAME in warnings[0]
        assert timer.delay_ms is not None

        assert timer.fire() is True
        assert register.count == 0

        bus.present = True
        assert timer.fire() is False
        assert register.count == 1
        assert len(warnings) == 1
