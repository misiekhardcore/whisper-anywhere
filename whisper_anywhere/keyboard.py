from evdev import InputDevice, list_devices, ecodes

CTRL = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
SUPER = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
SPACE = {ecodes.KEY_SPACE}
WANTED_MODS = CTRL | SUPER | SPACE


def find_keyboard():
    skip = {"ydotool", "lid", "power", "sleep", "video"}
    candidates = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except (OSError, PermissionError):
            continue
        name = dev.name.lower()
        if any(s in name for s in skip):
            continue
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            if ecodes.KEY_A in keys and ecodes.KEY_B in keys and ecodes.KEY_SPACE in keys:
                candidates.append(dev)

    if not candidates:
        raise RuntimeError(
            "no suitable keyboard found. Make sure you're in the 'input' group"
            " and have a physical keyboard connected."
        )

    # Prefer physical devices (non-empty phys = real hardware bus path) over
    # uinput/virtual ones (empty phys), then break ties by event number so
    # older/boot-time devices are preferred over late-created virtual devices.
    candidates.sort(key=lambda d: (not d.phys, int(d.path.rsplit("event", 1)[-1])))
    return candidates[0]


def keys_held(held):
    return bool(held & CTRL) and bool(held & SUPER) and bool(held & SPACE)
