import asyncio
import sys
from typing import Callable

from evdev import InputEvent, ecodes

from .audio import stop_recording
from .keyboard import Keyboard
from .output import TextOutput
from .recording import Recorder, Recording
from .state import DaemonState, StatusChannel, StatusServer
from .transcribe import Transcriber

KEYBOARD_SCAN_DELAY_S = 2
KEYBOARD_RECONNECT_DELAY_S = 1
RECORDING_RELEASE_TIMEOUT_S = 2

_RESCAN = object()


class Daemon:
    def __init__(
        self,
        hotkey_code: int | None,
        load_engine: Callable[[], Transcriber],
        output: TextOutput,
        language: str | None,
        status: StatusChannel | None = None,
    ) -> None:
        self._hotkey_code = hotkey_code
        self._load_engine = load_engine
        self._output = output
        self._language = language
        self._status = status or StatusServer()

    async def run(self) -> None:
        asyncio.get_running_loop().set_exception_handler(
            self._ignore_evdev_teardown_errors
        )
        await self._status.start()
        self._status.publish(DaemonState.LOADING)
        try:
            engine: Transcriber = await self._load()
            self._status.publish(DaemonState.IDLE)
            recorder = Recorder(engine, self._language, self._output, self._status)
            await self._listen(recorder)
        finally:
            await self._status.close()

    async def _load(self) -> Transcriber:
        """Load the engine off the event loop, so the status socket keeps answering meanwhile."""
        return await asyncio.get_running_loop().run_in_executor(None, self._load_engine)

    async def _listen(self, recorder: Recorder) -> None:
        while not self._status.quit_requested.is_set():
            try:
                devices = Keyboard.find_keyboards()
            except RuntimeError as exc:
                print(f"{exc} — retrying in {KEYBOARD_SCAN_DELAY_S}s", file=sys.stderr)
                await self._wait_or_quit(KEYBOARD_SCAN_DELAY_S)
                continue

            queue: asyncio.Queue = asyncio.Queue()
            readers = [
                asyncio.create_task(self._pump_device(dev, queue)) for dev in devices
            ]

            held: set[int] = set()
            recording: Recording | None = None
            try:
                while not self._status.quit_requested.is_set():
                    event = await self._next_event(queue)
                    if event is None:
                        break
                    if event.type != ecodes.EV_KEY:
                        continue

                    if event.value == 1:
                        starts: bool = self._press_starts_dictation(event, held)
                        if starts and recording is None:
                            self._status.publish(DaemonState.RECORDING)
                            recording = await Recorder.start()
                    elif event.value == 0:
                        ends: bool = self._release_ends_dictation(event, held)
                        if ends and recording is not None:
                            await recorder.finish(recording)
                            recording = None
            finally:
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                if recording is not None:
                    await self._discard(recording)
                if not self._status.quit_requested.is_set():
                    await asyncio.sleep(KEYBOARD_RECONNECT_DELAY_S)

    async def _next_event(self, queue: asyncio.Queue) -> object | None:
        """Return the next keyboard event, or None once quit is requested."""
        event_task = asyncio.create_task(queue.get())
        quit_task = asyncio.create_task(self._status.quit_requested.wait())
        done, pending = await asyncio.wait(
            {event_task, quit_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if quit_task in done:
            return None
        return event_task.result()

    async def _wait_or_quit(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._status.quit_requested.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    @staticmethod
    async def _discard(recording: Recording) -> None:
        """Release a capture that will never be transcribed."""
        stop_recording(recording.process)
        recording.reader.cancel()
        await asyncio.gather(recording.reader, return_exceptions=True)
        wait = getattr(recording.process, "wait", None)
        if not callable(wait):
            return
        try:
            await asyncio.wait_for(wait(), RECORDING_RELEASE_TIMEOUT_S)
        except (asyncio.TimeoutError, OSError):
            pass

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
