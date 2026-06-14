import atexit
import os
import sys

from .config import runtime_dir

LOCK_PATH = os.path.join(runtime_dir(), "lock")
_lock_fd = None


def acquire_lock():
    global _lock_fd
    try:
        import fcntl
    except ImportError:
        return
    _lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running.", file=sys.stderr)
        sys.exit(1)
    atexit.register(_remove_lock)


def _remove_lock():
    global _lock_fd
    if _lock_fd is None:
        return
    # Close the fd to release the flock, but leave the file in place. Unlinking
    # it would break exclusion during restart races: flock is keyed on the
    # inode, so a process that re-creates the path gets a fresh inode and locks
    # it independently, letting two daemons run at once.
    try:
        _lock_fd.close()
    except OSError:
        pass
    _lock_fd = None
