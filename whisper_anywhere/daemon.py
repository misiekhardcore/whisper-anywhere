import asyncio
import sys

from evdev import InputEvent, ecodes

from .audio import stop_recording
from .keyboard import Keyboard
from .output import TextOutput
from .recording import Recorder, Recording
from .transcribe import Transcriber

KEYBOARD_SCAN_DELAY_S = 2
KEYBOARD_RECONNECT_DELAY_S = 1

_RESCAN = object()


class Daemon:
    def __init__(
        self,
        hotkey_code: int | None,
        engine: Transcriber,
        output: TextOutput,
        language: str | None,
    ) -> None:
        self._hotkey_code = hotkey_code
        self._recorder = Recorder(engine, language, output)

    async def run(self) -> None:
        asyncio.get_running_loop().set_exception_handler(
            self._ignore_evdev_teardown_errors
        )

        while True:
            try:
                devices = Keyboard.find_keyboards()
            except RuntimeError as exc:
                print(f"{exc} — retrying in {KEYBOARD_SCAN_DELAY_S}s", file=sys.stderr)
                await asyncio.sleep(KEYBOARD_SCAN_DELAY_S)
                continue

            queue: asyncio.Queue = asyncio.Queue()
            readers = [
                asyncio.create_task(self._pump_device(dev, queue)) for dev in devices
            ]

            held: set[int] = set()
            recording: Recording | None = None
            try:
                while True:
                    event = await queue.get()
                    if event is _RESCAN:
                        print(
                            "keyboard disconnected; re-scanning devices",
                            file=sys.stderr,
                        )
                        break
                    if event.type != ecodes.EV_KEY:
                        continue

                    if event.value == 1:
                        starts: bool = self._press_starts_dictation(event, held)
                        if starts and recording is None:
                            recording = await Recorder.start()
                    elif event.value == 0:
                        ends: bool = self._release_ends_dictation(event, held)
                        if ends and recording is not None:
                            await self._recorder.finish(recording)
                            recording = None
            finally:
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                if recording is not None:
                    stop_recording(recording.process)
                await asyncio.sleep(KEYBOARD_RECONNECT_DELAY_S)

    def _press_starts_dictation(self, event: InputEvent, held: set[int]) -> bool:
        if self._hotkey_code is None:
            if event.code not in Keyboard.WANTED_MODS:
                return False
            held.add(event.code)
            return Keyboard.keys_held(held)
        return event.code == self._hotkey_code

    def _release_ends_dictation(self, event: InputEvent, held: set[int]) -> bool:
        if self._hotkey_code is None:
            if event.code not in Keyboard.WANTED_MODS:
                return False
            held.discard(event.code)
            return True
        return event.code == self._hotkey_code

    @staticmethod
    async def _pump_device(dev, queue: asyncio.Queue) -> None:
        try:
            async for event in dev.async_read_loop():
                await queue.put(event)
        except OSError:
            pass
        finally:
            await queue.put(_RESCAN)

    @staticmethod
    def _ignore_evdev_teardown_errors(loop, context: dict) -> None:
        if isinstance(context.get("exception"), asyncio.InvalidStateError):
            return
        loop.default_exception_handler(context)
