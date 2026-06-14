from unittest.mock import MagicMock, patch

from evdev import ecodes

from whisper_anywhere.keyboard import (
    CTRL,
    SPACE,
    SUPER,
    WANTED_MODS,
    find_keyboards,
    keys_held,
)


def _make_device(
    name: str,
    keys: tuple[int, ...] = (ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_SPACE),
    phys: str = "usb-0000:00:14.0-1/input0",
    event_num: int = 3,
) -> MagicMock:
    dev: MagicMock = MagicMock()
    dev.name = name
    dev.phys = phys
    dev.path = f"/dev/input/event{event_num}"
    dev.capabilities.return_value = {ecodes.EV_KEY: list(keys)}
    return dev


def _virtual(name: str, event_num: int = 10) -> MagicMock:
    return _make_device(name, phys="", event_num=event_num)


class TestFindKeyboards:
    def _run(self, devices: list[MagicMock]) -> list[MagicMock]:
        paths: list[str] = [dev.path for dev in devices]
        with (
            patch("whisper_anywhere.keyboard.list_devices", return_value=paths),
            patch("whisper_anywhere.keyboard.InputDevice", side_effect=devices),
        ):
            return find_keyboards()

    def test_returns_real_keyboard(self) -> None:
        real_kb: MagicMock = _make_device("AT Translated Set 2 keyboard")
        assert self._run([real_kb]) == [real_kb]

    def test_returns_all_physical_keyboards(self) -> None:
        builtin: MagicMock = _make_device("AT Translated Set 2 keyboard", event_num=4)
        external: MagicMock = _make_device("Logitech ERGO K860", event_num=12)
        assert self._run([builtin, external]) == [builtin, external]

    def test_skips_ydotool_virtual_device(self) -> None:
        virtual: MagicMock = _virtual("ydotool virtual device")
        real_kb: MagicMock = _make_device("USB Keyboard")
        assert self._run([virtual, real_kb]) == [real_kb]

    def test_skips_lid_and_power(self) -> None:
        lid: MagicMock = _make_device("Lid Switch")
        power: MagicMock = _make_device("Power Button")
        real_kb: MagicMock = _make_device("USB Keyboard")
        assert self._run([lid, power, real_kb]) == [real_kb]

    def test_raises_when_no_keyboard(self) -> None:
        import pytest

        virtual: MagicMock = _virtual("ydotool virtual device")
        with pytest.raises(RuntimeError, match="no suitable keyboard"):
            self._run([virtual])

    def test_skips_device_without_alpha_keys(self) -> None:
        import pytest

        no_alpha: MagicMock = _make_device(
            "Some Input Device", keys=(ecodes.KEY_VOLUMEUP,)
        )
        with pytest.raises(RuntimeError):
            self._run([no_alpha])

    def test_excludes_virtual_devices(self) -> None:
        virtual: MagicMock = _virtual("Unknown Virtual KB", event_num=2)
        real_kb: MagicMock = _make_device("USB Keyboard", event_num=5)
        assert self._run([virtual, real_kb]) == [real_kb]


class TestKeysHeld:
    def test_all_mods(self) -> None:
        held: set[int] = CTRL | SUPER | SPACE
        assert keys_held(held) is True

    def test_missing_ctrl(self) -> None:
        held: set[int] = SUPER | SPACE
        assert keys_held(held) is False

    def test_missing_super(self) -> None:
        held: set[int] = CTRL | SPACE
        assert keys_held(held) is False

    def test_missing_space(self) -> None:
        held: set[int] = CTRL | SUPER
        assert keys_held(held) is False

    def test_empty_set(self) -> None:
        assert keys_held(set()) is False

    def test_only_ctrl(self) -> None:
        assert keys_held(CTRL) is False

    def test_only_super(self) -> None:
        assert keys_held(SUPER) is False

    def test_only_space(self) -> None:
        assert keys_held(SPACE) is False

    def test_extra_keys_ignored(self) -> None:
        held: set[int] = CTRL | SUPER | SPACE | {ecodes.KEY_A, ecodes.KEY_B}
        assert keys_held(held) is True


class TestConstants:
    def test_wanted_mods_contains_ctrl(self) -> None:
        assert CTRL.issubset(WANTED_MODS)

    def test_wanted_mods_contains_super(self) -> None:
        assert SUPER.issubset(WANTED_MODS)

    def test_wanted_mods_contains_space(self) -> None:
        assert SPACE.issubset(WANTED_MODS)

    def test_ctrl_has_both(self) -> None:
        assert ecodes.KEY_LEFTCTRL in CTRL
        assert ecodes.KEY_RIGHTCTRL in CTRL

    def test_super_has_both(self) -> None:
        assert ecodes.KEY_LEFTMETA in SUPER
        assert ecodes.KEY_RIGHTMETA in SUPER

    def test_space_has_one(self) -> None:
        assert ecodes.KEY_SPACE in SPACE
        assert len(SPACE) == 1
