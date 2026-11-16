from __future__ import annotations

import logging
import multiprocessing as mp
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from typing import Any, Mapping, Type

from core.base_unit import BaseUnit, unit_entry

log = logging.getLogger("supervisor")


def _executable_for(unit_name: str) -> str:
    """Return a python.exe copy renamed after the unit so it shows up as
    ``unit_<name>.exe`` in Task Manager. Windows-only; a no-op elsewhere.

    Copies the *base* interpreter (not the venv redirector stub) into the
    venv's Scripts folder. That way:
      - Task Manager shows one process per unit, with the unit's name.
      - Python still finds ``pyvenv.cfg`` next door and activates the venv.
    Falls back to sys.executable if the copy can't be made.
    """
    if sys.platform != "win32":
        return sys.executable
    # Prefer the base interpreter so we don't inherit venv's launcher stub,
    # which would show up in Task Manager as an extra python.exe child.
    base = getattr(sys, "_base_executable", None) or sys.executable
    venv_scripts = Path(sys.executable).parent  # .../.venv/Scripts
    dst = venv_scripts / f"unit_{unit_name}.exe"
    if not dst.exists():
        try:
            shutil.copy2(base, dst)
        except OSError:
            log.warning("could not create renamed exe for %s, using %s", unit_name, base)
            return str(base)
    return str(dst)


@dataclass
class UnitSpec:
    cls: Type[BaseUnit]
    cfg: Mapping[str, Any]
    # Exponential backoff state for restarts.
    restarts: int = 0
    last_start: float = 0.0
    backoff_until: float = 0.0


@dataclass
class UnitStatus:
    name: str
    alive: bool
    pid: int | None
    restarts: int
    last_start: float
    exitcode: int | None = None
    stopped: bool = False


class Supervisor:
    """Starts, watches, restarts and stops worker-unit processes.

    ``units`` maps unit name -> (BaseUnit subclass, cfg dict).
    """

    POLL_INTERVAL = 5.0
    BACKOFF_BASE = 2.0
    BACKOFF_MAX = 60.0
    JOIN_TIMEOUT = 10.0

    def __init__(self, units: dict[str, tuple[Type[BaseUnit], Mapping[str, Any]]]) -> None:
        self._specs: dict[str, UnitSpec] = {
            name: UnitSpec(cls=cls, cfg=cfg) for name, (cls, cfg) in units.items()
        }
        self._procs: dict[str, mp.Process] = {}
        self._stop_events: dict[str, EventType] = {}
        # Units stopped through the API; the watch loop doesn't restart these.
        self._stopped: set[str] = set()
        self._global_stop: EventType = mp.Event()
        self._lock = threading.RLock()
        self._loop_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            for name in self._specs:
                self._start_unit(name)
        self._loop_thread = threading.Thread(
            target=self._watch_loop, name="supervisor-watch", daemon=True
        )
        self._loop_thread.start()
        log.info("supervisor started with units: %s", list(self._specs))

    def shutdown(self) -> None:
        log.info("supervisor shutting down")
        self._global_stop.set()
        with self._lock:
            for ev in self._stop_events.values():
                ev.set()
            procs = list(self._procs.items())
        for name, p in procs:
            p.join(self.JOIN_TIMEOUT)
            if p.is_alive():
                log.warning("unit %s did not exit in %ss, terminating", name, self.JOIN_TIMEOUT)
                p.terminate()
                p.join(5)
        if self._loop_thread:
            self._loop_thread.join(timeout=5)
        log.info("supervisor stopped")

    # -- control API hooks -------------------------------------------------

    def list_units(self) -> list[UnitStatus]:
        with self._lock:
            out = []
            for name, spec in self._specs.items():
                p = self._procs.get(name)
                out.append(
                    UnitStatus(
                        name=name,
                        alive=bool(p and p.is_alive()),
                        pid=p.pid if p else None,
                        restarts=spec.restarts,
                        last_start=spec.last_start,
                        exitcode=p.exitcode if p and not p.is_alive() else None,
                        stopped=name in self._stopped,
                    )
                )
            return out

    def stop_unit(self, name: str) -> bool:
        with self._lock:
            if name not in self._specs:
                return False
            self._stopped.add(name)
            ev = self._stop_events.get(name)
            if ev:
                ev.set()
            p = self._procs.get(name)
        if p:
            p.join(self.JOIN_TIMEOUT)
            if p.is_alive():
                p.terminate()
                p.join(5)
        with self._lock:
            self._procs.pop(name, None)
            self._stop_events.pop(name, None)
        log.info("stopped unit %s; it stays stopped until started again", name)
        return True

    def start_unit(self, name: str) -> bool:
        with self._lock:
            if name not in self._specs:
                return False
            self._stopped.discard(name)
            if name in self._procs and self._procs[name].is_alive():
                return True
            self._specs[name].backoff_until = 0.0
            self._start_unit(name)
            return True

    def is_healthy(self) -> bool:
        with self._lock:
            return all(p.is_alive() for p in self._procs.values()) if self._procs else False

    # -- internals ---------------------------------------------------------

    def _start_unit(self, name: str) -> None:
        spec = self._specs[name]
        now = time.monotonic()
        if now < spec.backoff_until:
            return
        stop_event = mp.Event()
        # Rename the child exe so Task Manager shows unit_<name>.exe.
        # set_executable is a global on the spawn context, but _start_unit
        # is serialized by _lock so there's no race.
        mp.set_executable(_executable_for(name))
        proc = mp.Process(
            target=unit_entry,
            args=(spec.cls, spec.cfg, stop_event),
            name=f"unit:{name}",
            daemon=False,
        )
        proc.start()
        self._procs[name] = proc
        self._stop_events[name] = stop_event
        spec.last_start = time.time()
        log.info("started unit %s pid=%s", name, proc.pid)

    def _watch_loop(self) -> None:
        while not self._global_stop.is_set():
            with self._lock:
                dead: list[str] = []
                for name, p in self._procs.items():
                    if not p.is_alive():
                        dead.append(name)
                for name in dead:
                    p = self._procs.pop(name)
                    self._stop_events.pop(name, None)
                    if name in self._stopped:
                        continue
                    spec = self._specs[name]
                    spec.restarts += 1
                    delay = min(self.BACKOFF_MAX, self.BACKOFF_BASE ** min(spec.restarts, 6))
                    spec.backoff_until = time.monotonic() + delay
                    log.warning(
                        "unit %s died exitcode=%s, restart in %.1fs (attempt %d)",
                        name, p.exitcode, delay, spec.restarts,
                    )
                for name in self._specs:
                    if name not in self._procs and name not in self._stopped:
                        self._start_unit(name)  # respects backoff_until
            if self._global_stop.wait(self.POLL_INTERVAL):
                return
