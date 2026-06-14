import asyncio
from unittest.mock import MagicMock

from evdev import ecodes


def _key_event(code, value):
    event = MagicMock()
    event.type = ecodes.EV_KEY
    event.code = code
    event.value = value
    return event


class _FakeDevice:
    def __init__(self, events):
        self._events = events

    async def async_read_loop(self):
        for event in self._events:
            await asyncio.sleep(0)
            yield event
        await asyncio.sleep(3600)


def _async_mock():
    m = MagicMock()

    async def async_wait():
        return 0

    m.wait = async_wait
    return m


class _MockVAD:
    def detect(self, audio, rate):
        return [(0, 1000)]

    def reset(self):
        pass
