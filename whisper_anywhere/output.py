import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from ctypes import (
    CDLL,
    POINTER,
    byref,
    c_int,
    c_uint32,
    c_void_p,
    cast,
)


class Typer(ABC):
    @abstractmethod
    def type_text(self, text: str) -> None:
        ...

    @abstractmethod
    def backspace(self, n: int) -> None:
        ...


_XKB_EVDEV_OFFSET = 8
_XKB_KEY_SHIFT_L = 0xFFE1
_XKB_KEY_SHIFT_R = 0xFFE2
_XKB_KEY_ISO_LEVEL3_SHIFT = 0xFE03


class KeycodeTyper(Typer):
    _SOCKET_PATHS = [
        "/tmp/.ydotool_socket",
    ]

    def __init__(self) -> None:
        self._lib: CDLL | None = None
        self._keymap: int | None = None
        self._socket_path: str | None = None
        self._l3_keycode: int | None = None
        self._lookup: dict[int, tuple[int, int]] = {}
        self._init()

    def _socket_path_candidates(self) -> list[str]:
        candidates: list[str] = []
        env = os.environ.get("YDOTOOL_SOCKET")
        if env:
            candidates.append(env)
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            candidates.append(os.path.join(xdg, ".ydotool_socket"))
        candidates.extend(self._SOCKET_PATHS)
        return candidates

    def _init(self) -> None:
        try:
            lib = CDLL("libxkbcommon.so.0")
        except OSError:
            return

        for p in self._socket_path_candidates():
            if os.path.exists(p):
                self._socket_path = p
                break
        if not self._socket_path:
            return

        lib.xkb_context_new.restype = c_void_p
        ctx = lib.xkb_context_new(0)
        if not ctx:
            return
        lib.xkb_context_unref.argtypes = [c_void_p]
        self._ctx = ctx

        lib.xkb_keymap_new_from_names.restype = c_void_p
        lib.xkb_keymap_new_from_names.argtypes = [c_void_p, c_void_p, c_int]
        km = lib.xkb_keymap_new_from_names(ctx, None, 0)
        if not km:
            return
        lib.xkb_keymap_unref.argtypes = [c_void_p]
        self._keymap = km
        self._lib = lib

        lib.xkb_keymap_min_keycode.restype = c_uint32
        lib.xkb_keymap_min_keycode.argtypes = [c_void_p]
        lib.xkb_keymap_max_keycode.restype = c_uint32
        lib.xkb_keymap_max_keycode.argtypes = [c_void_p]
        min_kc = lib.xkb_keymap_min_keycode(km)
        max_kc = lib.xkb_keymap_max_keycode(km)

        lib.xkb_keymap_key_get_syms_by_level.restype = c_int
        lib.xkb_keymap_key_get_syms_by_level.argtypes = [
            c_void_p, c_uint32, c_int, c_int, POINTER(c_void_p),
        ]

        lookup: dict[int, tuple[int, int]] = {}
        l3_kc: int | None = None

        for kc in range(min_kc, max_kc + 1):
            for level in range(4):
                syms_out = c_void_p()
                n = lib.xkb_keymap_key_get_syms_by_level(
                    km, kc, 0, level, byref(syms_out)
                )
                if n > 0 and syms_out.value:
                    ptr_type = POINTER(c_uint32)
                    p = cast(syms_out, ptr_type)
                    for i in range(n):
                        ks = p[i]
                        if ks not in lookup:
                            lookup[ks] = (kc, level)
                        if ks == _XKB_KEY_ISO_LEVEL3_SHIFT:
                            l3_kc = kc

        self._lookup = lookup
        self._l3_keycode = l3_kc

    def _get_kc(self, keysym: int, fallback_xkb: int = 0) -> int:
        entry = self._lookup.get(keysym)
        if entry is not None:
            return entry[0]
        return fallback_xkb

    def _evdev_code(self, xkb_kc: int) -> int:
        return xkb_kc - _XKB_EVDEV_OFFSET

    def _modifier_codes(self, level: int) -> list[int]:
        codes: list[int] = []
        if level == 0:
            return codes
        if level == 1:
            codes.append(self._evdev_code(self._get_kc(_XKB_KEY_SHIFT_L, 50)))
            return codes
        if level >= 2 and self._l3_keycode is not None:
            codes.append(self._evdev_code(self._l3_keycode))
        if level == 1 or level == 3:
            codes.append(self._evdev_code(self._get_kc(_XKB_KEY_SHIFT_L, 50)))
        return codes

    def _send_event(self, ev_type: int, code: int, value: int) -> None:
        if not self._socket_path:
            return
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.connect(self._socket_path)
            t = time.time()
            sec = int(t)
            usec = int((t - sec) * 1000000)
            event = struct.pack("llHHi", sec, usec, ev_type, code, value)
            sock.send(event)
            syn = struct.pack("llHHi", sec, usec, 0, 0, 0)
            sock.send(syn)
            sock.close()
        except (OSError, struct.error):
            pass

    def _press_key(self, code: int) -> None:
        self._send_event(1, code, 1)

    def _release_key(self, code: int) -> None:
        self._send_event(1, code, 0)

    def _tap_key(self, code: int) -> None:
        self._press_key(code)
        time.sleep(0.01)
        self._release_key(code)

    def _type_key_with_modifiers(self, keycode: int, level: int) -> None:
        modifiers = self._modifier_codes(level)
        for m in modifiers:
            self._press_key(m)
        time.sleep(0.005)
        self._tap_key(keycode)
        for m in reversed(modifiers):
            self._release_key(m)

    def _type_unicode_hex(self, keysym: int) -> None:
        lctrl = self._evdev_code(self._get_kc(0xFFE3, 37))
        lshift = self._evdev_code(self._get_kc(_XKB_KEY_SHIFT_L, 50))
        hex_str = format(keysym, "x")
        self._press_key(lctrl)
        self._press_key(lshift)
        time.sleep(0.005)
        self._tap_key(self._evdev_code(self._get_kc(0x75, 30)))
        self._release_key(lshift)
        self._release_key(lctrl)
        time.sleep(0.01)
        for ch in hex_str:
            ks = ord(ch)
            kc = self._get_kc(ks)
            if kc:
                self._tap_key(self._evdev_code(kc))
            time.sleep(0.005)
        self._tap_key(self._evdev_code(self._get_kc(0x20, 65)))

    def type_text(self, text: str) -> None:
        if not text:
            return
        if self._keymap is None:
            self._ydotool_fallback(text)
            return

        for char in text:
            ks = ord(char)
            entry = self._lookup.get(ks)
            if entry is not None:
                kc, level = entry
                self._type_key_with_modifiers(kc, level)
            elif ks < 128:
                self._ydotool_fallback(char)
            else:
                self._type_unicode_hex(ks)

    def _ydotool_fallback(self, text: str) -> None:
        try:
            subprocess.run(["ydotool", "type", text])
        except FileNotFoundError:
            pass

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        ev_code = self._evdev_code(self._get_kc(0xFF08, 22))
        for _ in range(n):
            self._tap_key(ev_code)


class WtypeTyper(Typer):
    @staticmethod
    def _check_compositor() -> bool:
        try:
            subprocess.run(
                ["wtype", "-k", "Ctrl"],
                capture_output=True,
                timeout=2,
                check=True,
            )
            return True
        except (
            FileNotFoundError,
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
        ):
            return False

    def type_text(self, text: str) -> None:
        if not text:
            return
        try:
            result = subprocess.run(["wtype", text])
        except FileNotFoundError:
            print(
                "wtype not found — install it: sudo apt install wtype",
                file=sys.stderr,
            )
            return
        if result.returncode != 0:
            print(f"wtype failed (exit {result.returncode})", file=sys.stderr)

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        try:
            subprocess.run(["wtype"] + ["-k", "BackSpace"] * n)
        except FileNotFoundError:
            print(
                "wtype not found — install it: sudo apt install wtype",
                file=sys.stderr,
            )


class YdotoolTyper(Typer):
    _KEY_BACKSPACE = 14

    def type_text(self, text: str) -> None:
        if not text:
            return
        try:
            result = subprocess.run(["ydotool", "type", text])
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )
            return
        if result.returncode != 0:
            print(
                f"ydotool type failed (exit {result.returncode}) — "
                "is ydotool.service running? (systemctl --user status ydotool)",
                file=sys.stderr,
            )

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        keys = [f"{self._KEY_BACKSPACE}:1", f"{self._KEY_BACKSPACE}:0"] * n
        try:
            subprocess.run(["ydotool", "key"] + keys)
        except FileNotFoundError:
            print(
                "ydotool not found — is it installed and on PATH?",
                file=sys.stderr,
            )


class TextOutput:
    def __init__(self, stdout_mode: bool) -> None:
        self._stdout_mode = stdout_mode
        self._typer: Typer | None = None

    @staticmethod
    def _probe_typer() -> Typer | None:
        if shutil.which("wtype") and WtypeTyper._check_compositor():
            return WtypeTyper()
        keycode = KeycodeTyper()
        if keycode._keymap is not None:
            return keycode
        if shutil.which("ydotool"):
            return YdotoolTyper()
        return None

    def _get_typer(self) -> Typer:
        if self._typer is None:
            self._typer = self._probe_typer()
            if self._typer is None:
                print(
                    "No typing tool found — ensure ydotool is installed and its service is running.",
                    file=sys.stderr,
                )
                print("  bash install.sh", file=sys.stderr)
                sys.exit(1)
        return self._typer

    def emit(self, text: str | None) -> None:
        if not text:
            return
        if self._stdout_mode:
            print(json.dumps({"text": text}), flush=True)
            return
        self._get_typer().type_text(text)

    def emit_partial(self, prev_text: str, new_text: str) -> None:
        if prev_text == new_text:
            return
        if self._stdout_mode:
            print(json.dumps({"type": "partial", "text": new_text}), flush=True)
            return
        prefix_len = self._common_prefix_len(prev_text, new_text)
        del_len = len(prev_text) - prefix_len
        suffix = new_text[prefix_len:]
        self._get_typer().backspace(del_len)
        if suffix:
            self._get_typer().type_text(suffix)

    def emit_final(self, prev_text: str, final_text: str) -> None:
        if self._stdout_mode:
            if final_text:
                print(json.dumps({"type": "final", "text": final_text}), flush=True)
            return
        if prev_text == final_text:
            return
        prefix_len = self._common_prefix_len(prev_text, final_text)
        del_len = len(prev_text) - prefix_len
        suffix = final_text[prefix_len:]
        self._get_typer().backspace(del_len)
        if suffix:
            self._get_typer().type_text(suffix)

    @staticmethod
    def _common_prefix_len(a: str, b: str) -> int:
        n = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                break
            n += 1
        return n
