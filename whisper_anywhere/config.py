import argparse
import os
import subprocess
import sys

from whisper_anywhere.transcribe import (
    DEFAULT_ENGINE_ID,
    FasterWhisperTranscriber,
    SenseVoiceTranscriber,
    VoskTranscriber,
)
from whisper_anywhere.vad import FsmnVAD


class Config:
    CONFIG_DIR: str = os.path.expanduser("~/.config/whisper-anywhere")

    @staticmethod
    def _get_version() -> str:
        try:
            from importlib.metadata import version

            return version("whisper-anywhere")
        except Exception:
            return "unknown"

    @staticmethod
    def runtime_dir() -> str:
        base = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
        path = os.path.join(base, "whisper-anywhere")
        os.makedirs(path, mode=0o700, exist_ok=True)
        return path

    @staticmethod
    def check_deps(engine_id: str = DEFAULT_ENGINE_ID) -> None:
        missing = []
        if not subprocess.run(["which", "parec"], capture_output=True).returncode == 0:
            missing.append("parec")
        if missing:
            print(f"Missing dependencies: {', '.join(missing)}", file=sys.stderr)
            print("Run: sudo apt install pulseaudio-utils", file=sys.stderr)
            sys.exit(1)
        try:
            from evdev import InputDevice  # noqa: F401
        except ImportError:
            print(
                "Missing python3-evdev. Run: pkexec apt install python3-evdev",
                file=sys.stderr,
            )
            sys.exit(1)
        match engine_id:
            case FasterWhisperTranscriber.ENGINE_ID:
                try:
                    from faster_whisper import WhisperModel  # noqa: F401
                except ImportError:
                    print(
                        "Missing faster-whisper. Run: pip3 install --user faster-whisper",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            case SenseVoiceTranscriber.ENGINE_ID | FsmnVAD.ENGINE_ID:
                try:
                    import funasr  # noqa: F401
                except ImportError:
                    print(
                        "Missing funasr. Run: pip3 install --user funasr",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            case VoskTranscriber.ENGINE_ID:
                try:
                    import vosk  # noqa: F401
                except ImportError:
                    print(
                        "Missing vosk. Run: pip3 install --user vosk",
                        file=sys.stderr,
                    )
                    sys.exit(1)

    @staticmethod
    def load_config(path: str | None = None) -> dict[str, str]:
        if path is None:
            path = os.path.join(Config.CONFIG_DIR, "config")
        cfg: dict[str, str] = {}
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, _, v = line.partition("=")
                        cfg[k.strip()] = v.strip()
        return cfg

    @staticmethod
    def parse_args() -> argparse.Namespace:
        p = argparse.ArgumentParser(
            description="whisper-anywhere voice dictation daemon"
        )
        p.add_argument(
            "--version",
            action="version",
            version=f"whisper-anywhere {Config._get_version()}",
            help="Show version and exit",
        )
        p.add_argument(
            "--hotkey",
            default=None,
            help="Single key like KEY_F12. Omit for Ctrl+Super+Space combo.",
        )
        p.add_argument(
            "--model", default=None, help="Model name (default: distil-medium.en)"
        )
        p.add_argument(
            "--language",
            default=None,
            help="Force a language code like en, pl, de. Omit to auto-detect.",
        )
        p.add_argument(
            "--engine",
            default=None,
            choices=(
                FasterWhisperTranscriber.ENGINE_ID,
                SenseVoiceTranscriber.ENGINE_ID,
                VoskTranscriber.ENGINE_ID,
            ),
            help="Transcription engine (default: sensevoice)",
        )
        p.add_argument(
            "--stdout",
            action="store_true",
            help="Write transcribed text as JSON lines to stdout instead of ydotool",
        )
        p.add_argument(
            "--vad",
            nargs="?",
            default=None,
            const=FsmnVAD.ENGINE_ID,
            metavar="ENGINE",
            help="VAD engine for live streaming (default: fsmn-vad). Use --vad=off to disable.",
        )
        return p.parse_args()

    @staticmethod
    def handler(signum: int, frame: object | None) -> None:
        raise SystemExit(0)
