from __future__ import annotations

import multiprocessing as mp
import threading
import time

from core.base_unit import BaseUnit
from core.supervisor import Supervisor


class _TickUnit(BaseUnit):
    name = "tick"

    def run(self) -> None:
        while not self.stop.is_set():
            if self.stop.wait(0.05):
                return


class _CrashOnceUnit(BaseUnit):
    """Crashes on its first incarnation, stays alive after restart."""

    name = "crashy"

    def setup(self) -> None:
        import os
        self._marker = os.path.join(self.cfg["tmp"], "started.once")
        self._first = not os.path.exists(self._marker)
        if self._first:
            open(self._marker, "w").close()

    def run(self) -> None:
        if self._first:
            raise RuntimeError("boom")
        while not self.stop.is_set():
            if self.stop.wait(0.05):
                return


class _SlowTeardownUnit(BaseUnit):
    """Takes a while to exit, so a stop_unit call stays in its join."""

    name = "slow"

    def run(self) -> None:
        while not self.stop.is_set():
            if self.stop.wait(0.05):
                return

    def teardown(self) -> None:
        time.sleep(1.0)


def test_supervisor_starts_and_stops(tmp_path):
    mp.set_start_method("spawn", force=True)
    sup = Supervisor({"tick": (_TickUnit, {})})
    sup.start()
    try:
        time.sleep(0.5)
        statuses = sup.list_units()
        assert len(statuses) == 1
        assert statuses[0].alive is True
    finally:
        sup.shutdown()


def test_supervisor_restarts_crashed_unit(tmp_path):
    mp.set_start_method("spawn", force=True)
    sup = Supervisor({"crashy": (_CrashOnceUnit, {"tmp": str(tmp_path)})})
    # Shorter poll so the test finishes quickly.
    sup.POLL_INTERVAL = 0.2
    sup.BACKOFF_BASE = 1.0
    sup.start()
    try:
        # Wait for the crash + restart cycle.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            statuses = sup.list_units()
            if statuses and statuses[0].restarts >= 1 and statuses[0].alive:
                break
            time.sleep(0.2)
        statuses = sup.list_units()
        assert statuses[0].restarts >= 1
        assert statuses[0].alive is True
    finally:
        sup.shutdown()


def test_stopped_unit_stays_stopped_until_started(tmp_path):
    mp.set_start_method("spawn", force=True)
    sup = Supervisor({"tick": (_TickUnit, {})})
    sup.POLL_INTERVAL = 0.2
    sup.start()
    try:
        assert sup.stop_unit("tick")
        time.sleep(1.5)  # several watch-loop passes, any of which used to restart it
        status = sup.list_units()[0]
        assert status.alive is False
        assert status.stopped is True
        assert status.restarts == 0

        assert sup.start_unit("tick")
        status = sup.list_units()[0]
        assert status.alive is True
        assert status.stopped is False
    finally:
        sup.shutdown()


def test_start_during_stop_leaves_unit_running(tmp_path):
    """A start that arrives while a stop is still waiting for the old process
    to exit must end with a fresh, running unit, not a stopped one."""
    mp.set_start_method("spawn", force=True)
    sup = Supervisor({"slow": (_SlowTeardownUnit, {})})
    sup.POLL_INTERVAL = 0.2
    sup.start()
    try:
        old_pid = sup.list_units()[0].pid

        stopper = threading.Thread(target=sup.stop_unit, args=("slow",))
        stopper.start()
        # Wait until stop_unit has marked the unit stopped and is joining.
        deadline = time.monotonic() + 5
        while not sup.list_units()[0].stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sup.list_units()[0].alive is True  # old process still exiting

        assert sup.start_unit("slow")
        stopper.join(timeout=20)
        assert not stopper.is_alive()

        status = sup.list_units()[0]
        assert status.alive is True
        assert status.stopped is False
        assert status.pid != old_pid
    finally:
        sup.shutdown()
