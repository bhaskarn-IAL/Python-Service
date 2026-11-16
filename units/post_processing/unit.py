from __future__ import annotations

import os

from core.base_unit import BaseUnit


class PostProcessingUnit(BaseUnit):
    """Post-processing stage - pretend to publish or persist final results."""

    name = "post_processing"

    def setup(self) -> None:
        self._interval = float(self.cfg.get("interval_seconds", 6.0))
        self._publishes = 0
        self.log.info("ready (interval=%.1fs, pid=%d)", self._interval, os.getpid())

    def run(self) -> None:
        while not self.stop.is_set():
            self._publishes += 1
            self.log.info("post_processing: published result #%d", self._publishes)
            if self.stop.wait(self._interval):
                return

    def teardown(self) -> None:
        self.log.info("stopped after %d publishes", self._publishes)
