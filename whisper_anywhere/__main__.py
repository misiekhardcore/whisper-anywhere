import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys

from evdev import ecodes

from .audio import write_wav, read_audio, AUDIO
from .config import check_deps, load_config, parse_args, handler
from .keyboard import find_keyboard, keys_held, WANTED_MODS

LOCK_PATH = "/tmp/whisper-anywhere.lock"
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
    proc.send_signal(signal.SIGINT)
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


async def run_daemon(hotkey_code, model, stdout_mode=False):
    dev = find_keyboard()
    held = set()
    proc = None
    read_task = None
    buffer = None

    async for event in dev.async_read_loop():
        if event.type != ecodes.EV_KEY:
            continue

        if hotkey_code is None:
            if event.code not in WANTED_MODS:
                continue
            if event.value == 1:
                held.add(event.code)
                if keys_held(held) and proc is None:
                    buffer = bytearray()
                    proc = await asyncio.create_subprocess_exec(
                        "parec", "--format=s16le", "--rate=16000",
                        "--channels=1", "--raw", "--latency-msec=30",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    read_task = asyncio.create_task(read_audio(proc, buffer))
            elif event.value == 0:
                held.discard(event.code)
                if proc is not None:
                    text = await transcribe(proc, read_task, buffer, model)
                    if text:
                        if stdout_mode:
                            print(json.dumps({"text": text}), flush=True)
                        else:
                            subprocess.run(["ydotool", "type", text])
                    proc = None
                    read_task = None
                    buffer = None
        else:
            if event.code != hotkey_code:
                continue
            if event.value == 1 and proc is None:
                buffer = bytearray()
                proc = await asyncio.create_subprocess_exec(
                    "parec", "--format=s16le", "--rate=16000",
                    "--channels=1", "--raw", "--latency-msec=30",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                read_task = asyncio.create_task(read_audio(proc, buffer))
            elif event.value == 0 and proc is not None:
                text = await transcribe(proc, read_task, buffer, model)
                if text:
                    if stdout_mode:
                        print(json.dumps({"text": text}), flush=True)
                    else:
                        subprocess.run(["ydotool", "type", text])
                proc = None
                read_task = None
                buffer = None


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
