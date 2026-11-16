"""Simple text-file log shared by the supervisor and every unit process.

    from core import log
    log.info("message")
    log.error("message")   # inside an except block, the traceback is added

Every process appends to the one file set by ``logging.path`` in
settings.yaml. Each line names the process that wrote it, for example::

    2026-11-16 16:47:24.616 INFO  [ingestion pid=20060] pulled batch #3

Writes are serialized across processes with a lock file next to the log
(``<log file>.lock``), so lines from different units never overlap.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_path: Path | None = None
_source = "supervisor"
_thread_lock = threading.Lock()

if sys.platform == "win32":
    import msvcrt

    def _acquire(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # retries for up to ~10 s

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def init(path: str | os.PathLike[str] | None, source: str = "supervisor") -> None:
    """Set the log file and the name this process writes under. Call once
    per process. With ``path=None``, info() and error() do nothing."""
    global _path, _source
    _source = source
    if path is None:
        _path = None
        return
    _path = Path(path)
    _path.parent.mkdir(parents=True, exist_ok=True)


def path() -> Path | None:
    """The current log file, so the supervisor can hand it to unit processes."""
    return _path


def info(message: str) -> None:
    _write("INFO", message)


def error(message: str) -> None:
    """Log an error. Called inside an ``except`` block, the traceback of the
    exception being handled is added below the message."""
    if sys.exc_info()[0] is not None:
        message = f"{message}\n{traceback.format_exc().rstrip()}"
    _write("ERROR", message)


def _write(level: str, message: str) -> None:
    if _path is None:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"{ts} {level:<5} [{_source} pid={os.getpid()}] {message}\n"
    try:
        with _thread_lock:
            fd = os.open(_path.with_name(_path.name + ".lock"), os.O_RDWR | os.O_CREAT)
            try:
                _acquire(fd)
                try:
                    with open(_path, "a", encoding="utf-8") as f:
                        f.write(line)
                finally:
                    _release(fd)
            finally:
                os.close(fd)
    except OSError as exc:
        # Logging must never take the service down; fall back to stderr.
        sys.stderr.write(f"log write failed ({exc}): {line}")
