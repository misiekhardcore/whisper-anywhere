import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys

from evdev import ecodes

from .audio import (
    write_wav,
    read_audio,
    stop_recording,
    AUDIO,
    SAMPLE_RATE,
    CHANNELS,
    PAREC_FORMAT,
    PAREC_LATENCY_MS,
)
from .config import check_deps, load_config, parse_args, handler, runtime_dir
from .keyboard import find_keyboards, keys_held, WANTED_MODS

LOCK_PATH = os.path.join(runtime_dir(), "lock")
_lock_fd = None

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


async def _live_vad_loop(
    buffer, model, language, emit_fn, vad, stop_event, stdout_mode
):
    """Periodically run VAD on accumulated audio, transcribe complete segments.

    Returns the byte offset up to which audio has been transcribed.
    """
    sample_width = 2
    sample_rate = 16000
    last_transcribed = 0
    min_segment = int(0.5 * sample_rate * sample_width)
    silence_threshold = int(0.5 * sample_rate * sample_width)
    force_boundary = 15 * sample_rate * sample_width

    consecutive_failures = 0
    max_consecutive_failures = 10

    while not stop_event.is_set():
        try:
            consecutive_failures = 0
            await asyncio.sleep(0.2)

            untranscribed = len(buffer) - last_transcribed
            if untranscribed < min_segment:
                continue

            chunk = bytes(buffer[last_transcribed:])
            segments = vad.detect(chunk, sample_rate)

            if not segments:
                continue

            chunk_base = last_transcribed
            for seg_start_sample, seg_end_sample in segments:
                seg_start = seg_start_sample * sample_width
                seg_end = seg_end_sample * sample_width
                seg_duration = seg_end - seg_start
                silence_after = untranscribed - seg_end

                complete = (
                    silence_after >= silence_threshold
                    or seg_duration >= force_boundary
                )

                if complete and seg_duration >= min_segment:
                    abs_start = chunk_base + seg_start
                    abs_end = chunk_base + seg_end

                    segment = bytes(buffer[abs_start:abs_end])

                    tmp = os.path.join(
                        runtime_dir(), f"live_{abs_start}_{abs_end}.wav"
                    )
                    try:
                        write_wav(tmp, segment)
                        text = await asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda t=tmp, l=language: model.transcribe(t, language=l),
                        )
                        if text:
                            emit_fn(text, stdout_mode)
                        last_transcribed = abs_end
                    finally:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
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

    return last_transcribed


async def _finish_recording(
    proc,
    read_task,
    buffer,
    model,
    language,
    stdout_mode,
    *,
    vad_task=None,
    live_mode=False,
    stop_vad=None,
):
    if live_mode and stop_vad is not None:
        stop_vad.set()
    if live_mode and vad_task is not None:
        last_transcribed = await vad_task
    else:
        last_transcribed = 0

    stop_recording(proc)
    await read_task
    await proc.wait()

    if not buffer:
        return

    if live_mode:
        remaining = buffer[last_transcribed:]
        if remaining:
            write_wav(AUDIO, bytes(remaining))
            text = await asyncio.get_running_loop().run_in_executor(
                None, lambda: model.transcribe(AUDIO, language=language)
            )
            emit(text, stdout_mode)
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
    live_mode=False,
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
                buffer, model, language, emit, vad, stop_vad, stdout_mode,
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
                            if live_mode:
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
                                live_mode=live_mode,
                                stop_vad=stop_vad,
                            )
                            proc = read_task = buffer = vad_task = stop_vad = None
                else:
                    if event.code != hotkey_code:
                        continue
                    if event.value == 1 and proc is None:
                        proc, read_task, buffer = await _start_recording()
                        if live_mode:
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
                            live_mode=live_mode,
                            stop_vad=stop_vad,
                        )
                        proc = read_task = buffer = vad_task = stop_vad = None
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            if proc is not None:
                if live_mode and stop_vad is not None:
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

    from .transcribe import load_model, DEFAULT_MODEL, DEFAULT_ENGINE

    engine = args.engine or cfg.get("engine", DEFAULT_ENGINE)
    check_deps(engine)
    model_id = args.model or cfg.get("model", DEFAULT_MODEL)
    model = load_model(model_id, engine=engine)

    live_mode = args.live or cfg.get("live") in ("1", "true", "yes")
    vad = None
    if live_mode:
        from .vad import load_vad

        vad_engine = cfg.get("vad_engine", "fsmn-vad")
        check_deps("sensevoice")
        vad = load_vad(vad_engine)

    language = args.language or cfg.get("language") or None
    lang_str = language or "auto-detect"
    live_str = ", live" if live_mode else ""

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
            live_mode=live_mode,
            vad=vad,
        )
    )


if __name__ == "__main__":
    main()
