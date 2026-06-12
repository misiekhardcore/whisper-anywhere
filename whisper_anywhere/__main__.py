import asyncio
import signal
import subprocess
import sys

from evdev import ecodes

from .audio import write_wav, read_audio, AUDIO
from .config import check_deps, load_config, parse_args, handler
from .keyboard import find_keyboard, keys_held, WANTED_MODS
from .transcribe import load_model, DEFAULT_MODEL


async def transcribe(proc, read_task, buffer, model):
    proc.send_signal(signal.SIGINT)
    await read_task
    await proc.wait()

    write_wav(AUDIO, buffer)

    def _run():
        segments, _ = model.transcribe(AUDIO, beam_size=5)
        return " ".join(segment.text.strip() for segment in segments)

    text = await asyncio.get_event_loop().run_in_executor(None, _run)
    if text:
        subprocess.run(["ydotool", "type", text])


async def run_daemon(hotkey_code, model):
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
                    await transcribe(proc, read_task, buffer, model)
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
                await transcribe(proc, read_task, buffer, model)
                proc = None
                read_task = None
                buffer = None


def main():
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    args = parse_args()
    cfg = load_config()

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

    check_deps()
    model_id = args.model or cfg.get("model", DEFAULT_MODEL)
    model = load_model(model_id)

    print(f"whisper-anywhere ready — mode: {mode_str}", file=sys.stderr)
    asyncio.run(run_daemon(hotkey_code, model))


if __name__ == "__main__":
    main()
