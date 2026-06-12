import os
from unittest.mock import patch

import pytest

from whisper_anywhere.__main__ import acquire_lock, _remove_lock, LOCK_PATH


class TestSingleInstance:
    def setup_method(self):
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass

    def test_acquire_creates_lock_file(self):
        assert not os.path.exists(LOCK_PATH)
        acquire_lock()
        try:
            assert os.path.exists(LOCK_PATH)
        finally:
            _remove_lock()

    def test_release_removes_lock_file(self):
        acquire_lock()
        _remove_lock()
        assert not os.path.exists(LOCK_PATH)

    def test_second_instance_denied(self):
        import fcntl

        fd1 = open(LOCK_PATH, "w")
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fd2 = open(LOCK_PATH, "w")
            with pytest.raises(OSError):
                fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd2.close()
        finally:
            fd1.close()
            os.remove(LOCK_PATH)

    def test_exits_when_locked(self):
        import fcntl

        fd = open(LOCK_PATH, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(SystemExit):
                acquire_lock()
        finally:
            fd.close()
            os.remove(LOCK_PATH)

    def test_idempotent_release(self):
        _remove_lock()
        _remove_lock()
