import asyncio
import sys
from typing import Optional

from evdev import ecodes

from .audio import stop_recording
from .keyboard import WANTED_MODS, find_keyboards, keys_held
from .output import TextOutput
from .recording import Recorder
from .transcribe import Transcriber
from .vad import VAD

KEYBOARD_SCAN_DELAY_S = 2
KEYBOARD_RECONNECT_DELAY_S = 1

_RESCAN = object()


class Daemon:
    def __init__(
        self,
        hotkey_code: Optional[int],
        engine: Transcriber,
        output: TextOutput,
        language: Optional[str],
        vad: Optional[VAD],
    ) -> None:
        self._hotkey_code = hotkey_code
        self._engine = engine
        self._output = output
        self._language = language
        self._vad = vad
        self._recorder = Recorder(engine, language, vad, output)

    async def run(self) -> None:
        asyncio.get_running_loop().set_exception_handler(
            self._ignore_evdev_teardown_errors
        )

        while True:
            try:
                devices = find_keyboards()
            except RuntimeError as exc:
                print(f"{exc} — retrying in {KEYBOARD_SCAN_DELAY_S}s", file=sys.stderr)
                await asyncio.sleep(KEYBOARD_SCAN_DELAY_S)
                continue

            queue = asyncio.Queue()
            readers = [
                asyncio.create_task(self._pump_device(dev, queue)) for dev in devices
            ]

            held = set()
            proc = None
            read_task = None
            buffer = None
            vad_task = None
            stop_vad = None
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

                    if self._hotkey_code is None:
                        if event.code not in WANTED_MODS:
                            continue
                        if event.value == 1:
                            held.add(event.code)
                            if keys_held(held) and proc is None:
                                proc, read_task, buffer = await Recorder.start()
                                if self._vad is not None:
                                    stop_vad, vad_task = self._start_vad_loop(buffer)
                        elif event.value == 0:
                            held.discard(event.code)
                            if proc is not None:
                                await self._recorder.finish(
                                    proc,
                                    read_task,
                                    buffer,
                                    vad_task=vad_task,
                                    stop_vad=stop_vad,
                                )
                                proc = read_task = buffer = vad_task = stop_vad = None
                    else:
                        if event.code != self._hotkey_code:
                            continue
                        if event.value == 1 and proc is None:
                            proc, read_task, buffer = await Recorder.start()
                            if self._vad is not None:
                                stop_vad, vad_task = self._start_vad_loop(buffer)
                        elif event.value == 0 and proc is not None:
                            await self._recorder.finish(
                                proc,
                                read_task,
                                buffer,
                                vad_task=vad_task,
                                stop_vad=stop_vad,
                            )
                            proc = read_task = buffer = vad_task = stop_vad = None
            finally:
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                if proc is not None:
                    if stop_vad is not None:
                        stop_vad.set()
                    stop_recording(proc)
                await asyncio.sleep(KEYBOARD_RECONNECT_DELAY_S)

    def _start_vad_loop(self, buffer: bytearray):
        stop_vad = asyncio.Event()
        self._vad.reset()
        vad_task = asyncio.create_task(
            self._recorder.live_vad_loop(buffer, stop_vad),
        )
        return stop_vad, vad_task

    @staticmethod
    async def _pump_device(dev, queue):
        try:
            async for event in dev.async_read_loop():
                await queue.put(event)
        except OSError:
            pass
        finally:
            await queue.put(_RESCAN)

    @staticmethod
    def _ignore_evdev_teardown_errors(loop, context):
        if isinstance(context.get("exception"), asyncio.InvalidStateError):
            return
        loop.default_exception_handler(context)
