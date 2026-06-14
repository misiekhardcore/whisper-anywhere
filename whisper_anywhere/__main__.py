import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys

from evdev import ecodes

from .audio import (
    AUDIO,
    CHANNELS,
    PAREC_FORMAT,
    PAREC_LATENCY_MS,
    SAMPLE_RATE,
    read_audio,
    stop_recording,
    write_wav,
)
from .config import check_deps, handler, load_config, parse_args, runtime_dir
from .keyboard import WANTED_MODS, find_keyboards, keys_held

LOCK_PATH = os.path.join(runtime_dir(), "lock")
_lock_fd = None

_SILENCE_THRESHOLD_S = 0.6

# How long to wait between keyboard re-scan attempts (device absent / hotplug).
KEYBOARD_SCAN_DELAY_S = 2
# How long to wait before re-scanning after a mid-session OSError (e.g. unplug).
KEYBOARD_RECONNECT_DELAY_S = 1


def acquire_lock():
    global _lock_fd
    try:
        import fcntl
    except ImportError:
        return
    _lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running.", file=sys.stderr)
        sys.exit(1)
    atexit.register(_remove_lock)


def _remove_lock():
    global _lock_fd
    if _lock_fd is None:
        return
    # Close the fd to release the flock, but leave the file in place. Unlinking
    # it would break exclusion during restart races: flock is keyed on the
    # inode, so a process that re-creates the path gets a fresh inode and locks
    # it independently, letting two daemons run at once.
    try:
        _lock_fd.close()
    except OSError:
        pass
    _lock_fd = None


async def transcribe(proc, read_task, buffer, model, language=None):
    stop_recording(proc)
    await read_task
    await proc.wait()

    if not buffer:
        return ""

    write_wav(AUDIO, buffer)

    def _run():
        return model.transcribe(AUDIO, language=language)

    text = await asyncio.get_running_loop().run_in_executor(None, _run)
    return text


_YDOTOOL_KEY_BACKSPACE = 14  # from /usr/include/linux/input-event-codes.h


def _backspace(n: int):
    if n <= 0:
        return
    keys = [f"{_YDOTOOL_KEY_BACKSPACE}:1", f"{_YDOTOOL_KEY_BACKSPACE}:0"] * n
    subprocess.run(["ydotool", "key"] + keys)


def emit(text, stdout_mode):
    """Deliver transcribed text, surfacing ydotool failures instead of dropping them."""
    if not text:
        return
    if stdout_mode:
        print(json.dumps({"text": text}), flush=True)
        return
    try:
        result = subprocess.run(["ydotool", "type", text])
    except FileNotFoundError:
        print("ydotool not found — is it installed and on PATH?", file=sys.stderr)
        return
    if result.returncode != 0:
        print(
            f"ydotool type failed (exit {result.returncode}) — "
            "is ydotool.service running? (systemctl --user status ydotool)",
            file=sys.stderr,
        )


def emit_partial(prev_text: str, new_text: str, stdout_mode: bool):
    if prev_text == new_text:
        return
    if stdout_mode:
        print(json.dumps({"type": "partial", "text": new_text}), flush=True)
        return
    try:
        _backspace(len(prev_text))
        if new_text:
            result = subprocess.run(["ydotool", "type", new_text])
            if result.returncode != 0:
                print(
                    f"ydotool type failed (exit {result.returncode}) — "
                    "is ydotool.service running? (systemctl --user status ydotool)",
                    file=sys.stderr,
                )
    except FileNotFoundError:
        print("ydotool not found — is it installed and on PATH?", file=sys.stderr)


def emit_final(prev_text: str, final_text: str, stdout_mode: bool):
    if stdout_mode:
        if final_text:
            print(json.dumps({"type": "final", "text": final_text}), flush=True)
        return
    try:
        _backspace(len(prev_text))
        if final_text:
            result = subprocess.run(["ydotool", "type", final_text])
            if result.returncode != 0:
                print(
                    f"ydotool type failed (exit {result.returncode}) — "
                    "is ydotool.service running? (systemctl --user status ydotool)",
                    file=sys.stderr,
                )
    except FileNotFoundError:
        print("ydotool not found — is it installed and on PATH?", file=sys.stderr)


async def _start_recording():
    buffer = bytearray()
    proc = await asyncio.create_subprocess_exec(
        "parec",
        f"--format={PAREC_FORMAT}",
        f"--rate={SAMPLE_RATE}",
        f"--channels={CHANNELS}",
        "--raw",
        f"--latency-msec={PAREC_LATENCY_MS}",
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )
    read_task = asyncio.create_task(read_audio(proc, buffer))
    return proc, read_task, buffer


async def _live_vad_loop(buffer, model, language, vad, stop_event, stdout_mode):
    """Emit complete speech segments in real-time.

    While a segment is in progress, updates the transcription in-place via
    emit_partial. Commits a high-quality final transcription at the end of each
    segment (silence gap >= _SILENCE_THRESHOLD_S).

    Returns (current_partial, tail_start) so _finish_recording can finalize
    any in-flight segment.
    """
    sample_rate = 16000
    sample_width = 2
    min_audio = int(0.25 * sample_rate * sample_width)
    silence_threshold_bytes = int(_SILENCE_THRESHOLD_S * sample_rate * sample_width)

    vad_pos = 0
    segment_start = 0
    last_speech_pos = 0
    in_segment = False
    current_partial = ""

    consecutive_failures = 0
    max_consecutive_failures = 10

    while not stop_event.is_set():
        try:
            consecutive_failures = 0
            await asyncio.sleep(0.2)

            current_pos = len(buffer)
            if current_pos < min_audio:
                continue

            new_audio = bytes(buffer[vad_pos:current_pos])
            segments = vad.detect(new_audio, sample_rate)

            if segments:
                if not in_segment:
                    segment_start = vad_pos
                    in_segment = True
                last_speech_pos = current_pos

                tmp = os.path.join(runtime_dir(), "live_segment.wav")
                try:
                    write_wav(tmp, bytes(buffer[segment_start:current_pos]))
                    text = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda t=tmp, lang=language: model.transcribe(t, language=lang),
                    )
                    if text != current_partial:
                        emit_partial(current_partial, text, stdout_mode)
                        current_partial = text
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            elif in_segment:
                silence_bytes = current_pos - last_speech_pos
                if silence_bytes >= silence_threshold_bytes:
                    tmp = os.path.join(runtime_dir(), "live_final.wav")
                    try:
                        write_wav(tmp, bytes(buffer[segment_start:last_speech_pos]))
                        final_text = await asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda t=tmp, lang=language: model.transcribe(
                                t, language=lang
                            ),
                        )
                        emit_final(current_partial, final_text, stdout_mode)
                        current_partial = ""
                        in_segment = False
                    finally:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass

            vad_pos = current_pos
        except Exception as exc:
            consecutive_failures += 1
            print(
                f"VAD loop error ({consecutive_failures}/{max_consecutive_failures}): {exc}",
                file=sys.stderr,
            )
            if consecutive_failures >= max_consecutive_failures:
                print(
                    "VAD loop: too many consecutive failures, stopping VAD loop",
                    file=sys.stderr,
                )
                break

    tail_start = segment_start if in_segment else vad_pos
    return current_partial, tail_start


async def _finish_recording(
    proc,
    read_task,
    buffer,
    model,
    language,
    stdout_mode,
    *,
    vad_task=None,
    stop_vad=None,
):
    if stop_vad is not None:
        stop_vad.set()

    current_partial = ""
    tail_start = 0
    if vad_task is not None:
        current_partial, tail_start = await vad_task

    stop_recording(proc)
    await read_task
    await proc.wait()

    if not buffer:
        return

    if vad_task is not None:
        tail = bytes(buffer[tail_start:])
        if not tail:
            return
        write_wav(AUDIO, tail)
        text = await asyncio.get_running_loop().run_in_executor(
            None, lambda: model.transcribe(AUDIO, language=language)
        )
        emit_final(current_partial, text, stdout_mode)
    else:
        write_wav(AUDIO, buffer)
        text = await asyncio.get_running_loop().run_in_executor(
            None, lambda: model.transcribe(AUDIO, language=language)
        )
        emit(text, stdout_mode)


# Sentinel pushed onto the event queue when a reader stops (device unplugged
# or errored) so the consumer wakes up and re-scans for keyboards.
_RESCAN = object()


def _ignore_evdev_teardown_errors(loop, context):
    # On SIGINT/SIGTERM the signal handler raises SystemExit mid-poll; evdev's
    # already-scheduled fd callback then fires on a finalized future and raises
    # InvalidStateError. It is harmless shutdown noise, so swallow just that.
    if isinstance(context.get("exception"), asyncio.InvalidStateError):
        return
    loop.default_exception_handler(context)


async def _pump_device(dev, queue):
    """Forward one device's key events into the shared queue until it stops."""
    try:
        async for event in dev.async_read_loop():
            await queue.put(event)
    except OSError:
        pass
    finally:
        await queue.put(_RESCAN)


async def run_daemon(
    hotkey_code,
    model,
    stdout_mode=False,
    language=None,
    vad=None,
):
    asyncio.get_running_loop().set_exception_handler(_ignore_evdev_teardown_errors)
    # Outer loop re-acquires keyboards whenever one disappears so the daemon
    # survives unplug/replug without user intervention.  The loop is
    # intentionally unbounded: a hotkey daemon should always recover.

    def _start_vad_loop():
        stop_vad = asyncio.Event()
        vad.reset()
        vad_task = asyncio.create_task(
            _live_vad_loop(
                buffer,
                model,
                language,
                vad,
                stop_vad,
                stdout_mode,
            )
        )
        return stop_vad, vad_task

    while True:
        try:
            devices = find_keyboards()
        except RuntimeError as exc:
            print(f"{exc} — retrying in {KEYBOARD_SCAN_DELAY_S}s", file=sys.stderr)
            await asyncio.sleep(KEYBOARD_SCAN_DELAY_S)
            continue

        # Read every keyboard concurrently and funnel events through one queue,
        # so the hotkey works on whichever keyboard the user presses it on while
        # state (held keys, recording) stays single-consumer and race-free.
        queue = asyncio.Queue()
        readers = [asyncio.create_task(_pump_device(dev, queue)) for dev in devices]

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
                    print("keyboard disconnected; re-scanning devices", file=sys.stderr)
                    break
                if event.type != ecodes.EV_KEY:
                    continue

                if hotkey_code is None:
                    if event.code not in WANTED_MODS:
                        continue
                    if event.value == 1:
                        held.add(event.code)
                        if keys_held(held) and proc is None:
                            proc, read_task, buffer = await _start_recording()
                            if vad is not None:
                                stop_vad, vad_task = _start_vad_loop()
                    elif event.value == 0:
                        held.discard(event.code)
                        if proc is not None:
                            await _finish_recording(
                                proc,
                                read_task,
                                buffer,
                                model,
                                language,
                                stdout_mode,
                                vad_task=vad_task,
                                stop_vad=stop_vad,
                            )
                            proc = read_task = buffer = vad_task = stop_vad = None
                else:
                    if event.code != hotkey_code:
                        continue
                    if event.value == 1 and proc is None:
                        proc, read_task, buffer = await _start_recording()
                        if vad is not None:
                            stop_vad, vad_task = _start_vad_loop()
                    elif event.value == 0 and proc is not None:
                        await _finish_recording(
                            proc,
                            read_task,
                            buffer,
                            model,
                            language,
                            stdout_mode,
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


def main():
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    acquire_lock()

    args = parse_args()
    cfg = load_config()
    stdout_mode = args.stdout or cfg.get("stdout") in ("1", "true", "yes")

    hotkey_arg = args.hotkey or cfg.get("hotkey")
    hotkey_code = None
    if hotkey_arg:
        hotkey_code = getattr(ecodes, hotkey_arg, None)
        if hotkey_code is None:
            print(f"Unknown key: {hotkey_arg}", file=sys.stderr)
            sys.exit(1)
        mode_str = f"single-key ({hotkey_arg})"
    else:
        mode_str = "combo (Ctrl+Super+Space)"

    from .transcribe import DEFAULT_ENGINE, load_model

    engine = args.engine or cfg.get("engine", DEFAULT_ENGINE)
    check_deps(engine)
    model_id = args.model or cfg.get("model") or None
    model = load_model(engine, model_id)

    vad = None
    vad_engine = args.vad or cfg.get("vad_engine")
    if vad_engine:
        from .vad import load_vad

        check_deps(vad_engine)
        vad = load_vad(vad_engine)

    language = args.language or cfg.get("language") or None
    lang_str = language or "auto-detect"
    live_str = f", live ({vad_engine})" if vad_engine else ""

    print(
        f"whisper-anywhere ready — mode: {mode_str}, language: {lang_str}{live_str}",
        file=sys.stderr,
    )
    asyncio.run(
        run_daemon(
            hotkey_code,
            model,
            stdout_mode,
            language,
            vad=vad,
        )
    )


if __name__ == "__main__":
    main()
