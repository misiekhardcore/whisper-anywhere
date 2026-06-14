import os
from io import TextIOWrapper

import pytest

from whisper_anywhere.lock import LOCK_PATH, Lock


class TestLock:
    def setup_method(self) -> None:
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass

    def test_acquire_creates_lock_file(self) -> None:
        assert not os.path.exists(LOCK_PATH)
        lock: Lock = Lock()
        lock.acquire()
        try:
            assert os.path.exists(LOCK_PATH)
        finally:
            lock.release()

    def test_release_frees_lock_for_reacquire(self) -> None:
        lock_a: Lock = Lock()
        lock_a.acquire()
        lock_a.release()
        lock_b: Lock = Lock()
        lock_b.acquire()
        try:
            assert os.path.exists(LOCK_PATH)
        finally:
            lock_b.release()

    def test_second_instance_denied(self) -> None:
        import fcntl

        fd1: TextIOWrapper = open(LOCK_PATH, "w")
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fd2: TextIOWrapper = open(LOCK_PATH, "w")
            with pytest.raises(OSError):
                fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd2.close()
        finally:
            fd1.close()
            os.remove(LOCK_PATH)

    def test_exits_when_locked(self) -> None:
        import fcntl

        fd: TextIOWrapper = open(LOCK_PATH, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(SystemExit):
                Lock().acquire()
        finally:
            fd.close()
            os.remove(LOCK_PATH)

    def test_idempotent_release(self) -> None:
        lock: Lock = Lock()
        lock.release()
        lock.release()
