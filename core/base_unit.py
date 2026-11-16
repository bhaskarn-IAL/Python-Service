from __future__ import annotations

import os
import signal
from multiprocessing.synchronize import Event as EventType
from typing import Any, Mapping, Type

from core import log


class BaseUnit:
    """Contract every worker unit implements.

    A unit runs inside its own OS process. The supervisor hands it a
    shared ``stop_event`` so it can shut down cleanly. Log with
    ``self.log.info("...")`` and ``self.log.error("...")``.
    """

    name: str = "base"

    def __init__(self, cfg: Mapping[str, Any], stop_event: EventType) -> None:
        self.cfg = dict(cfg or {})
        self.stop = stop_event
        self.log = log

    def setup(self) -> None:
        """Open resources (DB, sockets, files). Called once before run()."""

    def run(self) -> None:
        """Main loop. Must check ``self.stop.is_set()`` regularly."""
        raise NotImplementedError

    def teardown(self) -> None:
        """Close resources. Always runs, even if run() raised."""


def unit_entry(
    cls: Type[BaseUnit],
    cfg: Mapping[str, Any],
    stop_event: EventType,
    log_path: str | os.PathLike[str] | None = None,
) -> None:
    """Process entry point. Runs in the child process after spawn."""
    # Child processes ignore Ctrl+C directly; the supervisor sets stop_event.
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, AttributeError):
        pass

    log.init(log_path, source=cls.name)

    unit = cls(cfg, stop_event)
    try:
        log.info("setup")
        unit.setup()
        log.info("run")
        unit.run()
    except Exception:
        log.error("unit crashed")
        raise
    finally:
        try:
            unit.teardown()
            log.info("teardown complete")
        except Exception:
            log.error("teardown failed")
