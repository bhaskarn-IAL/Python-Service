from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s [pid=%(process)d] %(message)s"

# Built-in defaults, used only if neither env nor YAML provides a value.
_DEFAULT_LOG_DIR = "logs"
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_CONSOLE = "true"
_FALSY = {"0", "false", "no", "off"}


def _log_dir() -> Path:
    """Read env at call time so main.py can seed it from settings.yaml
    before configure_* runs, and so spawned children (which inherit env)
    see the same value.
    """
    return Path(os.environ.get("SERVICE_LOG_DIR", _DEFAULT_LOG_DIR))


def _log_level() -> str:
    return os.environ.get("SERVICE_LOG_LEVEL", _DEFAULT_LOG_LEVEL).upper()


def _log_console() -> bool:
    # Off under NSSM, which already captures stderr into service.err.log.
    value = os.environ.get("SERVICE_LOG_CONSOLE", _DEFAULT_LOG_CONSOLE)
    return value.strip().lower() not in _FALSY


def _file_handler(filename: str) -> logging.Handler:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / filename, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FMT))
    return handler


def _stream_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FMT))
    return handler


def configure_supervisor_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(_log_level())
    if _log_console():
        root.addHandler(_stream_handler())
    root.addHandler(_file_handler("supervisor.log"))


def configure_unit_logging(unit_name: str) -> None:
    """Called inside each worker process so its logs go to its own file."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(_log_level())
    if _log_console():
        root.addHandler(_stream_handler())
    root.addHandler(_file_handler(f"unit_{unit_name}.log"))


def apply_logging_config(cfg: dict | None) -> None:
    """Seed env vars from the YAML `logging` block so (a) configure_* uses
    them and (b) spawned child processes inherit them. Env vars already
    set (e.g. by systemd/NSSM) are preserved - deploy-time overrides win.
    """
    cfg = cfg or {}
    if "dir" in cfg:
        os.environ.setdefault("SERVICE_LOG_DIR", str(cfg["dir"]))
    if "level" in cfg:
        os.environ.setdefault("SERVICE_LOG_LEVEL", str(cfg["level"]).upper())
    if "console" in cfg:
        os.environ.setdefault("SERVICE_LOG_CONSOLE", str(cfg["console"]).lower())
