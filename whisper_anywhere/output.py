import json
import subprocess
import sys
from typing import Optional

_YDOTOOL_KEY_BACKSPACE = 14  # from /usr/include/linux/input-event-codes.h


def _backspace(n: int):
    if n <= 0:
        return
    keys = [f"{_YDOTOOL_KEY_BACKSPACE}:1", f"{_YDOTOOL_KEY_BACKSPACE}:0"] * n
    subprocess.run(["ydotool", "key"] + keys)


def emit(text: Optional[str], stdout_mode: bool):
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


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def emit_partial(prev_text: str, new_text: str, stdout_mode: bool):
    if prev_text == new_text:
        return
    if stdout_mode:
        print(json.dumps({"type": "partial", "text": new_text}), flush=True)
        return
    prefix_len = _common_prefix_len(prev_text, new_text)
    del_len = len(prev_text) - prefix_len
    suffix = new_text[prefix_len:]
    try:
        _backspace(del_len)
        if suffix:
            result = subprocess.run(["ydotool", "type", suffix])
            if result.returncode != 0:
                print(
                    f"ydotool type failed (exit {result.returncode}) — "
                    "is ydotool.service running? (systemctl --user status ydotool)",
                    file=sys.stderr,
                )
    except FileNotFoundError:
        print("ydotool not found — is it installed and on PATH?", file=sys.stderr)


def emit_final(prev_text: str, final_text: str, stdout_mode: bool):
    if stdout_mode:
        if final_text:
            print(json.dumps({"type": "final", "text": final_text}), flush=True)
        return
    if prev_text == final_text:
        return
    prefix_len = _common_prefix_len(prev_text, final_text)
    del_len = len(prev_text) - prefix_len
    suffix = final_text[prefix_len:]
    try:
        _backspace(del_len)
        if suffix:
            result = subprocess.run(["ydotool", "type", suffix])
            if result.returncode != 0:
                print(
                    f"ydotool type failed (exit {result.returncode}) — "
                    "is ydotool.service running? (systemctl --user status ydotool)",
                    file=sys.stderr,
                )
    except FileNotFoundError:
        print("ydotool not found — is it installed and on PATH?", file=sys.stderr)
