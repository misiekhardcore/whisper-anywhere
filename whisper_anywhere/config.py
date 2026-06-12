import argparse
import os
import subprocess
import sys

CONFIG_DIR = os.path.expanduser("~/.config/whisper-anywhere")


def check_deps():
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
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Missing faster-whisper. Run: pip3 install --user faster-whisper", file=sys.stderr)
        sys.exit(1)


def load_config():
    cfg_path = os.path.join(CONFIG_DIR, "config")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
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
                    help="Model name (default: distil-large-v3)")
    return p.parse_args()


def handler(signum, frame):
    raise SystemExit(0)
