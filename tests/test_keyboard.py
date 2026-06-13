from unittest.mock import MagicMock, patch

from evdev import ecodes

from whisper_anywhere.keyboard import keys_held, find_keyboard, CTRL, SUPER, SPACE, WANTED_MODS


def _make_device(name, keys=(ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_SPACE)):
    dev = MagicMock()
    dev.name = name
    dev.capabilities.return_value = {ecodes.EV_KEY: list(keys)}
    return dev


class TestFindKeyboard:
    def _run(self, devices):
        paths = [f"/dev/input/event{i}" for i in range(len(devices))]
        with patch("whisper_anywhere.keyboard.list_devices", return_value=paths), \
             patch("whisper_anywhere.keyboard.InputDevice", side_effect=devices):
            return find_keyboard()

    def test_returns_real_keyboard(self):
        real_kb = _make_device("AT Translated Set 2 keyboard")
        assert self._run([real_kb]) is real_kb

    def test_skips_ydotool_virtual_device(self):
        # ydotoold names its uinput device "ydotool virtual device"; it must
        # never be returned as the keyboard to listen on.
        virtual = _make_device("ydotool virtual device")
        real_kb = _make_device("USB Keyboard")
        assert self._run([virtual, real_kb]) is real_kb

    def test_skips_lid_and_power(self):
        lid = _make_device("Lid Switch")
        power = _make_device("Power Button")
        real_kb = _make_device("USB Keyboard")
        assert self._run([lid, power, real_kb]) is real_kb

    def test_raises_when_no_keyboard(self):
        import pytest
        virtual = _make_device("ydotool virtual device")
        with pytest.raises(RuntimeError, match="no suitable keyboard"):
            self._run([virtual])

    def test_skips_device_without_alpha_keys(self):
        import pytest
        no_alpha = _make_device("Some Input Device", keys=(ecodes.KEY_VOLUMEUP,))
        with pytest.raises(RuntimeError):
            self._run([no_alpha])


class TestKeysHeld:
    def test_all_mods(self):
        held = CTRL | SUPER | SPACE
        assert keys_held(held) is True

    def test_missing_ctrl(self):
        held = SUPER | SPACE
        assert keys_held(held) is False

    def test_missing_super(self):
        held = CTRL | SPACE
        assert keys_held(held) is False

    def test_missing_space(self):
        held = CTRL | SUPER
        assert keys_held(held) is False

    def test_empty_set(self):
        assert keys_held(set()) is False

    def test_only_ctrl(self):
        assert keys_held(CTRL) is False

    def test_only_super(self):
        assert keys_held(SUPER) is False

    def test_only_space(self):
        assert keys_held(SPACE) is False

    def test_extra_keys_ignored(self):
        held = CTRL | SUPER | SPACE | {ecodes.KEY_A, ecodes.KEY_B}
        assert keys_held(held) is True


class TestConstants:
    def test_wanted_mods_contains_ctrl(self):
        assert CTRL.issubset(WANTED_MODS)

    def test_wanted_mods_contains_super(self):
        assert SUPER.issubset(WANTED_MODS)

    def test_wanted_mods_contains_space(self):
        assert SPACE.issubset(WANTED_MODS)

    def test_ctrl_has_both(self):
        assert ecodes.KEY_LEFTCTRL in CTRL
        assert ecodes.KEY_RIGHTCTRL in CTRL

    def test_super_has_both(self):
        assert ecodes.KEY_LEFTMETA in SUPER
        assert ecodes.KEY_RIGHTMETA in SUPER

    def test_space_has_one(self):
        assert ecodes.KEY_SPACE in SPACE
        assert len(SPACE) == 1
