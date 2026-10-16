"""Exited parents must not hide live groups or race their own reap on Darwin."""

import os
import signal
import subprocess
import sys
from unittest.mock import Mock

import pytest

from agentic_workbench import runner
from agentic_workbench.errors import WorkbenchError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")


def test_group_exit_race_reaps_parent_and_retries_group_signal(monkeypatch):
    real_killpg = os.killpg
    attempts = []
    parent = (
        "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(20)']); print('ready',flush=True)"
    )
    with subprocess.Popen(
        [sys.executable, "-c", parent], stdout=subprocess.PIPE, start_new_session=True
    ) as process:
        assert process.stdout is not None
        assert process.stdout.readline() == b"ready\n"
        # Reproduce the CI window: EPERM arrives before a poll observes the exit.
        monkeypatch.setattr(process, "poll", lambda: None)

        def exiting_group(pid, sig):
            assert pid == process.pid and sig == signal.SIGKILL
            attempts.append(pid)
            if len(attempts) == 1:
                raise PermissionError("exiting process group")
            return real_killpg(pid, sig)

        monkeypatch.setattr(runner.os, "killpg", exiting_group)
        try:
            runner._kill(process)
            assert process.wait(timeout=5) == 0
            # EOF requires the inheriting descendant to be stopped, not just its parent.
            assert process.communicate(timeout=5)[0] == b""
            assert len(attempts) == 2
        finally:
            try:
                real_killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_permission_denied_group_is_not_ignored_when_parent_exited(monkeypatch):
    process = Mock(spec=subprocess.Popen, pid=12345)
    process.poll.return_value = 0
    process.wait.return_value = 0
    monkeypatch.setattr(runner.os, "killpg", Mock(side_effect=PermissionError))
    with pytest.raises(WorkbenchError, match="EXECUTION_ERROR"):
        runner._kill(process)


def test_permission_denied_live_parent_remains_a_bounded_error(monkeypatch):
    process = Mock(spec=subprocess.Popen, pid=12345)
    process.poll.return_value = None
    process.wait.side_effect = subprocess.TimeoutExpired("owned command", 5)
    monkeypatch.setattr(runner.os, "killpg", Mock(side_effect=PermissionError))
    with pytest.raises(WorkbenchError, match="EXECUTION_ERROR"):
        runner._kill(process)
