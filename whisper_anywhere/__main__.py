import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys

from evdev import ecodes

from .audio import write_wav, read_audio, stop_recording, AUDIO
from .config import check_deps, load_config, parse_args, handler, runtime_dir
from .keyboard import find_keyboard, keys_held, WANTED_MODS

LOCK_PATH = os.path.join(runtime_dir(), "lock")
_lock_fd = None


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
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass
    _lock_fd = None


async def transcribe(proc, read_task, buffer, model):
    stop_recording(proc)
    await read_task
    await proc.wait()

    if not buffer:
        return ""

    write_wav(AUDIO, buffer)

    def _run():
        segments, _ = model.transcribe(AUDIO, beam_size=5)
        return " ".join(segment.text.strip() for segment in segments)

    text = await asyncio.get_event_loop().run_in_executor(None, _run)
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
        "parec", "--format=s16le", "--rate=16000",
        "--channels=1", "--raw", "--latency-msec=30",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    read_task = asyncio.create_task(read_audio(proc, buffer))
    return proc, read_task, buffer


async def run_daemon(hotkey_code, model, stdout_mode=False):
    # Outer loop re-acquires the keyboard if it is unplugged/replugged so the
    # daemon recovers instead of silently going dead.
    while True:
        try:
            dev = find_keyboard()
        except RuntimeError as exc:
            print(f"{exc} — retrying in 2s", file=sys.stderr)
            await asyncio.sleep(2)
            continue

        held = set()
        proc = None
        read_task = None
        buffer = None
        try:
            async for event in dev.async_read_loop():
                if event.type != ecodes.EV_KEY:
                    continue

                if hotkey_code is None:
                    if event.code not in WANTED_MODS:
                        continue
                    if event.value == 1:
                        held.add(event.code)
                        if keys_held(held) and proc is None:
                            proc, read_task, buffer = await _start_recording()
                    elif event.value == 0:
                        held.discard(event.code)
                        if proc is not None:
                            text = await transcribe(proc, read_task, buffer, model)
                            emit(text, stdout_mode)
                            proc = read_task = buffer = None
                else:
                    if event.code != hotkey_code:
                        continue
                    if event.value == 1 and proc is None:
                        proc, read_task, buffer = await _start_recording()
                    elif event.value == 0 and proc is not None:
                        text = await transcribe(proc, read_task, buffer, model)
                        emit(text, stdout_mode)
                        proc = read_task = buffer = None
        except OSError as exc:
            print(f"keyboard input error ({exc}); re-scanning devices", file=sys.stderr)
            if proc is not None:
                stop_recording(proc)
            await asyncio.sleep(1)


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

    from .transcribe import load_model, DEFAULT_MODEL

    check_deps()
    model_id = args.model or cfg.get("model", DEFAULT_MODEL)
    model = load_model(model_id)

    print(f"whisper-anywhere ready — mode: {mode_str}", file=sys.stderr)
    asyncio.run(run_daemon(hotkey_code, model, stdout_mode))


if __name__ == "__main__":
    main()
