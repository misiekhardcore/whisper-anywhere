import asyncio
import signal
import sys
from argparse import Namespace

from evdev import ecodes

from .config import Config
from .daemon import Daemon
from .insertion import select_insertion
from .lock import Lock
from .output import TextOutput
from .transcribe import Transcriber


def load_hotkey(cfg: dict, args: Namespace) -> int | None:
    hotkey_arg = args.hotkey or cfg.get("hotkey")
    hotkey_code: int | None = None
    if hotkey_arg:
        hotkey_code = getattr(ecodes, hotkey_arg, None)
        if hotkey_code is None:
            print(f"Unknown key: {hotkey_arg}", file=sys.stderr)
            sys.exit(1)
    return hotkey_code


def load_engine(
    cfg: dict,
    args: Namespace,
    language: str | None = None,
    require_insertion: bool = True,
) -> Transcriber:
    from .transcribe import DEFAULT_ENGINE_ID, load_engine

    engine_id = args.engine or cfg.get("engine", DEFAULT_ENGINE_ID)
    Config.check_deps(engine_id, require_insertion)
    model_id = args.model or cfg.get("model")
    return load_engine(engine_id, model_id, language)


def main():
    signal.signal(signal.SIGINT, Config.handler)
    signal.signal(signal.SIGTERM, Config.handler)

    Lock().acquire()

    args = Config.parse_args()
    cfg = Config.load_config()
    stdout_mode: bool = args.stdout or cfg.get("stdout") in ("1", "true", "yes")

    hotkey_code = load_hotkey(cfg, args)
    language = args.language or cfg.get("language")
    engine = load_engine(cfg, args, language, require_insertion=not stdout_mode)

    selection = None if stdout_mode else select_insertion()
    if selection is not None and selection.inserter is None:
        print(selection.description, file=sys.stderr)
        sys.exit(1)
    output = TextOutput(stdout_mode, selection.inserter if selection else None)
    insertion: str = "stdout" if stdout_mode else selection.description
    daemon = Daemon(hotkey_code, engine, output, language)

    lang_str = language or "auto-detect"
    print(
        f"whisper-anywhere ready — engine: {engine.ENGINE_ID}, hotkey: {f'single-key ({hotkey_code})' if hotkey_code is not None else 'combo (Ctrl+Super+Space)'}, language: {lang_str}, stdout: {stdout_mode}, insertion: {insertion}",
        file=sys.stderr,
    )

    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
