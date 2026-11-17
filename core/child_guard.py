"""Make sure unit processes die with their supervisor, even if the supervisor
is force-killed (Task Manager "End task", ``Stop-Process -Force``, ``kill -9``,
a crash).

Two layers:

1. ``bind_to_this_process(pid)`` runs in the supervisor. On Windows it puts
   the unit into a Job Object with "kill on job close". The job's only handle
   belongs to the supervisor, so when the supervisor process ends, however it
   ends, Windows closes the handle and kills every unit in the job (and any
   process a unit started). This is immediate, so ``teardown()`` does not run.
   On Linux it does nothing; layer 2 covers it there.

2. ``watch_parent(stop_event)`` runs in each unit. A background thread waits
   for the supervisor process to end. When it does, the thread sets the unit's
   stop event, so the unit finishes its current loop and runs ``teardown()``
   like a normal stop. If the unit is still alive ``PARENT_GONE_GRACE``
   seconds later, the thread ends the process with ``os._exit``.

On Windows, layer 1 normally wins, and layer 2 is the fallback if a unit
could not be added to the job. On Linux, layer 2 is what stops the units.
(Linux's ``PR_SET_PDEATHSIG`` is deliberately not used: it fires when the
parent *thread* that started the child exits, and units restarted through
the API are started from short-lived worker threads.)
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import threading
from multiprocessing.synchronize import Event as EventType

from core import log

# How long a unit gets to stop cleanly after its supervisor disappears.
PARENT_GONE_GRACE = 10.0


# -- layer 1: Windows Job Object (in the supervisor) ------------------------

_job = None  # one job per supervisor process, kept open for its lifetime
_job_lock = threading.Lock()

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _BasicLimitInfo(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )
        ]

    class _ExtendedLimitInfo(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInfo),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _create_job():
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _ExtendedLimitInfo()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(job)
            raise ctypes.WinError(err)
        return job

    def _assign(pid: int) -> None:
        global _job
        with _job_lock:
            if _job is None:
                _job = _create_job()
            handle = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not _kernel32.AssignProcessToJobObject(_job, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _kernel32.CloseHandle(handle)


def bind_to_this_process(pid: int) -> bool:
    """Have the OS kill process ``pid`` when this process ends (Windows).
    Returns False, after logging why, if that couldn't be set up; the unit's
    own parent watcher still stops it in that case. No-op on other systems."""
    if sys.platform != "win32":
        return True
    try:
        _assign(pid)
        return True
    except OSError as exc:
        log.error(f"could not tie pid={pid} to the supervisor's lifetime ({exc}); "
                  "relying on the unit's parent watcher")
        return False


# -- layer 2: parent watcher (in each unit) ----------------------------------

def watch_parent(stop_event: EventType, grace: float = PARENT_GONE_GRACE) -> None:
    """Start a background thread that stops this unit if its supervisor dies.
    Call once, early, in the unit process."""
    parent = mp.parent_process()
    if parent is None:  # not started by multiprocessing
        return

    def _hard_exit() -> None:
        log.error(f"still running {grace:g}s after the supervisor died; exiting now")
        os._exit(1)

    def _watch() -> None:
        parent.join()  # returns only once the supervisor process has ended
        log.error("supervisor process is gone; stopping this unit")
        # Arm the deadline first: if the supervisor died while holding the
        # stop event's internal lock, stop_event.set() below could block.
        deadline = threading.Timer(grace, _hard_exit)
        deadline.daemon = True
        deadline.start()
        stop_event.set()

    threading.Thread(target=_watch, name="parent-watch", daemon=True).start()
