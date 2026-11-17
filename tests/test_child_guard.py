"""Units must not outlive a supervisor that is force-killed."""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

from core.base_unit import BaseUnit, unit_entry
from core.supervisor import Supervisor


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32")
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)  # POSIX only; on Windows os.kill would terminate it
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


class _PidUnit(BaseUnit):
    """Writes <dir>/<name>.pid in setup and <dir>/<name>.teardown in teardown."""

    name = "pidunit"

    def setup(self) -> None:
        self._dir = Path(self.cfg["dir"])
        (self._dir / f"{self.cfg['tag']}.pid").write_text(str(os.getpid()))

    def run(self) -> None:
        while not self.stop.is_set():
            if self.stop.wait(0.05):
                return

    def teardown(self) -> None:
        (self._dir / f"{self.cfg['tag']}.teardown").write_text("done")


def _run_supervisor(directory: str) -> None:
    """Runs in its own process: a real supervisor with two units, forever."""
    sup = Supervisor({
        "a": (_PidUnit, {"dir": directory, "tag": "a"}),
        "b": (_PidUnit, {"dir": directory, "tag": "b"}),
    })
    sup.start()
    while True:
        time.sleep(1)


def _run_bare_parent(directory: str) -> None:
    """Runs in its own process: starts one unit with plain multiprocessing (no
    supervisor, so no Windows job), forever. Only the parent watcher can stop it."""
    ctx = mp.get_context("spawn")
    proc = ctx.Process(
        target=unit_entry, args=(_PidUnit, {"dir": directory, "tag": "c"}, ctx.Event())
    )
    proc.start()
    while True:
        time.sleep(1)


def _start_and_wait_for_pids(target, directory: Path, tags: list[str]):
    parent = mp.get_context("spawn").Process(target=target, args=(str(directory),))
    parent.start()
    files = [directory / f"{t}.pid" for t in tags]
    assert _wait_for(lambda: all(f.exists() and f.read_text() for f in files), 30), \
        "units never started"
    pids = [int(f.read_text()) for f in files]
    assert all(_alive(p) for p in pids)
    return parent, pids


def test_units_die_when_supervisor_is_force_killed(tmp_path):
    parent, pids = _start_and_wait_for_pids(_run_supervisor, tmp_path, ["a", "b"])
    try:
        parent.kill()  # TerminateProcess on Windows, SIGKILL on Linux
        parent.join(10)
        # Windows: the job kills them at once. Linux: the parent watcher
        # stops them, at most PARENT_GONE_GRACE seconds later.
        assert _wait_for(lambda: not any(_alive(p) for p in pids), 20), \
            f"units still running after the supervisor was killed: {pids}"
    finally:
        if parent.is_alive():
            parent.kill()


def test_parent_watcher_runs_teardown_when_parent_is_killed(tmp_path):
    parent, pids = _start_and_wait_for_pids(_run_bare_parent, tmp_path, ["c"])
    try:
        parent.kill()
        parent.join(10)
        assert _wait_for(lambda: (tmp_path / "c.teardown").exists(), 20), \
            "unit did not run teardown() after its parent was killed"
        assert _wait_for(lambda: not _alive(pids[0]), 20)
    finally:
        if parent.is_alive():
            parent.kill()
