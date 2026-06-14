import asyncio
import signal
import sys
from argparse import Namespace
from typing import Optional

from evdev import ecodes

from .config import check_deps, handler, load_config, parse_args
from .daemon import Daemon
from .lock import Lock
from .output import TextOutput
from .transcribe import Transcriber
from .vad import VAD


def load_hotkey(cfg: dict, args: Namespace) -> Optional[int]:
    hotkey_arg = args.hotkey or cfg.get("hotkey")
    hotkey_code: Optional[int] = None
    if hotkey_arg:
        hotkey_code = getattr(ecodes, hotkey_arg, None)
        if hotkey_code is None:
            print(f"Unknown key: {hotkey_arg}", file=sys.stderr)
            sys.exit(1)
    return hotkey_code


def load_engine(cfg: dict, args: Namespace) -> Transcriber:
    from .transcribe import DEFAULT_ENGINE_ID, load_engine

    engine_id = args.engine or cfg.get("engine", DEFAULT_ENGINE_ID)
    check_deps(engine_id)
    model_id = args.model or cfg.get("model")
    return load_engine(engine_id, model_id)


def load_vad(cfg: dict, args: Namespace) -> Optional[VAD]:
    from .vad import DEFAULT_VAD_ENGINE, load_vad

    vad_engine_id = args.vad or cfg.get("vad_engine", DEFAULT_VAD_ENGINE)
    if vad_engine_id.lower() in ("off", "false", "0"):
        return None
    check_deps(vad_engine_id)
    return load_vad(vad_engine_id)


def main():
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    Lock().acquire()

    args = parse_args()
    cfg = load_config()
    stdout_mode = (args.stdout or cfg.get("stdout")) in ("1", "true", "yes")

    hotkey_code = load_hotkey(cfg, args)
    engine = load_engine(cfg, args)
    vad = load_vad(cfg, args)
    language = args.language or cfg.get("language")

    output = TextOutput(stdout_mode)
    daemon = Daemon(hotkey_code, engine, output, language, vad)

    lang_str = language or "auto-detect"
    print(
        f"whisper-anywhere ready — engine: {engine.ENGINE_ID}, hotkey: {f'single-key ({hotkey_code})' if hotkey_code is not None else 'combo (Ctrl+Super+Space)'}, language: {lang_str}{f', live ({vad.ENGINE_ID})' if vad else ''}, stdout: {stdout_mode}",
        file=sys.stderr,
    )

    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
