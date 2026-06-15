import asyncio
import signal
import sys
from argparse import Namespace

from evdev import ecodes

from .config import Config
from .daemon import Daemon
from .lock import Lock
from .output import TextOutput
from .transcribe import Transcriber
from .vad import VAD


def load_hotkey(cfg: dict, args: Namespace) -> int | None:
    hotkey_arg = args.hotkey or cfg.get("hotkey")
    hotkey_code: int | None = None
    if hotkey_arg:
        hotkey_code = getattr(ecodes, hotkey_arg, None)
        if hotkey_code is None:
            print(f"Unknown key: {hotkey_arg}", file=sys.stderr)
            sys.exit(1)
    return hotkey_code


def load_engine(cfg: dict, args: Namespace, language: str | None = None) -> Transcriber:
    from .transcribe import DEFAULT_ENGINE_ID, load_engine

    engine_id = args.engine or cfg.get("engine", DEFAULT_ENGINE_ID)
    Config.check_deps(engine_id)
    model_id = args.model or cfg.get("model")
    return load_engine(engine_id, model_id, language)


def load_vad(cfg: dict, args: Namespace) -> VAD | None:
    from .vad import DEFAULT_VAD_ENGINE, load_vad

    vad_engine_id = args.vad or cfg.get("vad_engine", DEFAULT_VAD_ENGINE)
    if vad_engine_id.lower() in ("off", "false", "0"):
        return None
    Config.check_deps(vad_engine_id)
    return load_vad(vad_engine_id)


def main():
    signal.signal(signal.SIGINT, Config.handler)
    signal.signal(signal.SIGTERM, Config.handler)

    Lock().acquire()

    args = Config.parse_args()
    cfg = Config.load_config()
    stdout_mode = (args.stdout or cfg.get("stdout")) in ("1", "true", "yes")

    hotkey_code = load_hotkey(cfg, args)
    language = args.language or cfg.get("language")
    engine = load_engine(cfg, args, language)
    vad = load_vad(cfg, args)

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
