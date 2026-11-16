from __future__ import annotations

import os

from core.base_unit import BaseUnit


class PreProcessingUnit(BaseUnit):
    """Pre-processing stage - pretend to validate and clean incoming data."""

    name = "pre_processing"

    def setup(self) -> None:
        self._interval = float(self.cfg.get("interval_seconds", 4.0))
        self._cycles = 0
        self.log.info("ready (interval=%.1fs, pid=%d)", self._interval, os.getpid())

    def run(self) -> None:
        while not self.stop.is_set():
            self._cycles += 1
            self.log.info("pre_processing: cleaned+validated cycle #%d", self._cycles)
            if self.stop.wait(self._interval):
                return

    def teardown(self) -> None:
        self.log.info("stopped after %d cycles", self._cycles)
