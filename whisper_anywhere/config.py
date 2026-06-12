import argparse
import os
import subprocess
import sys

CONFIG_DIR = os.path.expanduser("~/.config/whisper-anywhere")


def runtime_dir():
    """Per-user, non-world-writable dir for the lock and temp audio.

    Prefers $XDG_RUNTIME_DIR (tmpfs, mode 0700, cleaned on logout); falls back
    to ~/.cache. Created with 0700 so other users can't read recorded audio.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
    path = os.path.join(base, "whisper-anywhere")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def check_deps(engine="faster-whisper"):
    missing = []
    for cmd in ("parec", "ydotool"):
        if not subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            missing.append(cmd)
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}", file=sys.stderr)
        print("Run the install script:", file=sys.stderr)
        print("  bash install.sh", file=sys.stderr)
        sys.exit(1)
    try:
        from evdev import InputDevice
    except ImportError:
        print("Missing python3-evdev. Run: pkexec apt install python3-evdev", file=sys.stderr)
        sys.exit(1)
    if engine == "faster-whisper":
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            print("Missing faster-whisper. Run: pip3 install --user faster-whisper", file=sys.stderr)
            sys.exit(1)
    elif engine == "sensevoice":
        try:
            import funasr  # noqa: F401
        except ImportError:
            print("Missing funasr. Run: pip3 install --user funasr", file=sys.stderr)
            sys.exit(1)


def load_config(path=None):
    if path is None:
        path = os.path.join(CONFIG_DIR, "config")
    cfg = {}
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


def parse_args():
    p = argparse.ArgumentParser(description="whisper-anywhere voice dictation daemon")
    p.add_argument("--hotkey", default=None,
                    help="Single key like KEY_F12. Omit for Ctrl+Super+Space combo.")
    p.add_argument("--model", default=None,
                    help="Model name (default: distil-medium.en)")
    p.add_argument("--language", default=None,
                    help="Force a language code like en, pl, de. Omit to auto-detect.")
    p.add_argument("--engine", default=None, choices=("faster-whisper", "sensevoice"),
                    help="Transcription engine (default: faster-whisper)")
    p.add_argument("--stdout", action="store_true",
                    help="Write transcribed text as JSON lines to stdout instead of ydotool")
    return p.parse_args()


def handler(signum, frame):
    raise SystemExit(0)
