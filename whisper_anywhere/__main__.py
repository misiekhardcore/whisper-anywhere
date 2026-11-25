import asyncio
import signal
import sys
from argparse import Namespace
from dataclasses import dataclass
from typing import Callable

from evdev import ecodes

from .config import Config
from .daemon import Daemon
from .insertion import InsertionSelection, select_insertion
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


@dataclass(frozen=True)
class EngineSetup:
    """The configured engine, loaded only once the daemon has published loading."""

    engine_id: str
    load: Callable[[], Transcriber]


def plan_engine(
    cfg: dict,
    args: Namespace,
    language: str | None = None,
    insertion: InsertionSelection | None = None,
) -> EngineSetup:
    from .transcribe import DEFAULT_ENGINE_ID, load_engine

    engine_id = args.engine or cfg.get("engine", DEFAULT_ENGINE_ID)
    Config.check_deps(engine_id, insertion)
    model_id = args.model or cfg.get("model")
    return EngineSetup(engine_id, lambda: load_engine(engine_id, model_id, language))


def main():
    signal.signal(signal.SIGINT, Config.handler)
    signal.signal(signal.SIGTERM, Config.handler)

    Lock().acquire()

    args = Config.parse_args()
    cfg = Config.load_config()
    stdout_mode: bool = args.stdout or cfg.get("stdout") in ("1", "true", "yes")

    hotkey_code = load_hotkey(cfg, args)
    language = args.language or cfg.get("language")
    selection: InsertionSelection | None = None if stdout_mode else select_insertion()
    setup = plan_engine(cfg, args, language, selection)

    output = TextOutput(stdout_mode, selection.inserter if selection else None)
    insertion: str = "stdout" if stdout_mode else selection.description
    daemon = Daemon(hotkey_code, setup.load, output, language)

    lang_str = language or "auto-detect"
    print(
        f"whisper-anywhere starting — engine: {setup.engine_id}, hotkey: {f'single-key ({hotkey_code})' if hotkey_code is not None else 'combo (Ctrl+Super+Space)'}, language: {lang_str}, stdout: {stdout_mode}, insertion: {insertion}",
        file=sys.stderr,
    )

    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
