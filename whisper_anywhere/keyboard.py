from evdev import InputDevice, list_devices, ecodes

CTRL = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
SUPER = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
SPACE = {ecodes.KEY_SPACE}
WANTED_MODS = CTRL | SUPER | SPACE


def find_keyboards():
    """Return every physical keyboard, so the daemon can listen on all of them.

    Picking a single device is unreliable when more than one keyboard is
    connected (e.g. a laptop's built-in keyboard plus an external one): the
    user could press the hotkey on any of them. We therefore return all real
    keyboards and let the caller read every device concurrently.
    """
    skip = {"ydotool", "lid", "power", "sleep", "video"}
    keyboards = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except (OSError, PermissionError):
            continue
        # Empty phys = uinput/virtual device (e.g. ydotoold). Never listen on
        # these or we would capture our own injected keystrokes.
        if not dev.phys:
            continue
        name = dev.name.lower()
        if any(s in name for s in skip):
            continue
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            if (
                ecodes.KEY_A in keys
                and ecodes.KEY_B in keys
                and ecodes.KEY_SPACE in keys
            ):
                keyboards.append(dev)

    if not keyboards:
        raise RuntimeError(
            "no suitable keyboard found. Make sure you're in the 'input' group"
            " and have a physical keyboard connected."
        )

    return keyboards


def keys_held(held):
    return bool(held & CTRL) and bool(held & SUPER) and bool(held & SPACE)
