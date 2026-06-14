import asyncio
from typing import AsyncGenerator
from unittest.mock import MagicMock

from evdev import InputEvent, ecodes


def _key_event(code: int, value: int) -> MagicMock:
    event: MagicMock = MagicMock(spec=InputEvent)
    event.type = ecodes.EV_KEY
    event.code = code
    event.value = value
    return event


class _FakeDevice:
    def __init__(self, events: list[MagicMock]) -> None:
        self._events = events

    async def async_read_loop(self) -> AsyncGenerator[MagicMock, None]:
        for event in self._events:
            await asyncio.sleep(0)
            yield event
        await asyncio.sleep(3600)


def _async_mock() -> MagicMock:
    m: MagicMock = MagicMock()

    async def async_wait() -> int:
        return 0

    m.wait = async_wait
    return m


class _MockVAD:
    def detect(self, audio: bytes, rate: int) -> list[tuple[int, int]]:
        return [(0, 1000)]

    def reset(self) -> None:
        pass
