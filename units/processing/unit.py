from __future__ import annotations

import os

from core.base_unit import BaseUnit


class ProcessingUnit(BaseUnit):
    """Processing stage - pretend to run the main business logic."""

    name = "processing"

    def setup(self) -> None:
        self._interval = float(self.cfg.get("interval_seconds", 5.0))
        self._runs = 0
        self.log.info("ready (interval=%.1fs, pid=%d)", self._interval, os.getpid())

    def run(self) -> None:
        while not self.stop.is_set():
            self._runs += 1
            self.log.info("processing: completed run #%d", self._runs)
            if self.stop.wait(self._interval):
                return

    def teardown(self) -> None:
        self.log.info("stopped after %d runs", self._runs)
