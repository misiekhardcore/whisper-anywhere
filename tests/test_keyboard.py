from evdev import ecodes

from whisper_anywhere.keyboard import keys_held, CTRL, SUPER, SPACE, WANTED_MODS


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
