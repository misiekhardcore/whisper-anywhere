from evdev import InputDevice, list_devices, ecodes

CTRL = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
SUPER = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
SPACE = {ecodes.KEY_SPACE}
WANTED_MODS = CTRL | SUPER | SPACE


def find_keyboard():
    skip = {"ydotoold", "lid", "power", "sleep", "video"}
    for path in list_devices():
        dev = InputDevice(path)
        name = dev.name.lower()
        if any(s in name for s in skip):
            continue
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            if ecodes.KEY_A in keys and ecodes.KEY_B in keys and ecodes.KEY_SPACE in keys:
                return dev
    raise RuntimeError(
        "no suitable keyboard found. Make sure you're in the 'input' group"
        " and have a physical keyboard connected."
    )


def keys_held(held):
    return bool(held & CTRL) and bool(held & SUPER) and bool(held & SPACE)
