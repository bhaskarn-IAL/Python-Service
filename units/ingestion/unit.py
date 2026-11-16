from __future__ import annotations

import os

from core.base_unit import BaseUnit


class IngestionUnit(BaseUnit):
    """Ingestion stage - pretend to pull raw data from some source."""

    name = "ingestion"

    def setup(self) -> None:
        self._interval = float(self.cfg.get("interval_seconds", 3.0))
        self._batches = 0
        self.log.info("ready (interval=%.1fs, pid=%d)", self._interval, os.getpid())

    def run(self) -> None:
        while not self.stop.is_set():
            self._batches += 1
            self.log.info("ingestion: pulled batch #%d from source", self._batches)
            if self.stop.wait(self._interval):
                return

    def teardown(self) -> None:
        self.log.info("stopped after %d batches", self._batches)
