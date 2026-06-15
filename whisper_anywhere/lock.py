import atexit
import os
import sys

from .config import Config

LOCK_PATH = os.path.join(Config.runtime_dir(), "lock")


class Lock:
    def __init__(self) -> None:
        self._fd: int | None = None

    def acquire(self) -> None:
        try:
            import fcntl
        except ImportError:
            return
        self._fd = open(LOCK_PATH, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("Another instance is already running.", file=sys.stderr)
            sys.exit(1)
        atexit.register(self.release)

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            self._fd.close()
        except OSError:
            pass
        self._fd = None
