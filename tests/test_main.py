import json
import os
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.__main__ import acquire_lock, _remove_lock, emit, LOCK_PATH


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


class TestEmit:
    def test_empty_text_is_noop(self):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            emit("", False)
            run.assert_not_called()

    def test_stdout_mode_writes_json(self, capsys):
        emit("hello world", True)
        out = capsys.readouterr().out
        assert json.loads(out) == {"text": "hello world"}

    def test_ydotool_invoked(self):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            emit("hello", False)
            run.assert_called_once_with(["ydotool", "type", "hello"])

    def test_ydotool_failure_warns(self, capsys):
        with patch("whisper_anywhere.__main__.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1)
            emit("hello", False)
            assert "ydotool type failed" in capsys.readouterr().err

    def test_ydotool_missing_warns(self, capsys):
        with patch("whisper_anywhere.__main__.subprocess.run", side_effect=FileNotFoundError):
            emit("hello", False)
            assert "ydotool not found" in capsys.readouterr().err
