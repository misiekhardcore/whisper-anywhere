from evdev import InputDevice, ecodes, list_devices


class Keyboard:
    CTRL: set[int] = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
    SUPER: set[int] = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
    SPACE: set[int] = {ecodes.KEY_SPACE}
    WANTED_MODS: set[int] = CTRL | SUPER | SPACE

    @staticmethod
    def find_keyboards() -> list[InputDevice]:
        skip: set[str] = {"ydotool", "lid", "power", "sleep", "video"}
        keyboards: list[InputDevice] = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
            except (OSError, PermissionError):
                continue
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

    @classmethod
    def keys_held(cls, held: set[int]) -> bool:
        return (
            bool(held & cls.CTRL)
            and bool(held & cls.SUPER)
            and bool(held & cls.SPACE)
        )
