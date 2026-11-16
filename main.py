from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import sys
from pathlib import Path
from typing import Any, Mapping, Type

import uvicorn
import yaml

from api.control import build_app
from core.base_unit import BaseUnit
from core.logging_setup import apply_logging_config, configure_supervisor_logging
from core.registry import resolve
from core.supervisor import Supervisor

CONFIG_PATH = Path(__file__).with_name("config") / "settings.yaml"
log = logging.getLogger("main")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_units(
    config: dict[str, Any],
) -> dict[str, tuple[Type[BaseUnit], Mapping[str, Any]]]:
    """Resolve enabled units from config. Units are independent of each other."""
    units: dict[str, tuple[Type[BaseUnit], Mapping[str, Any]]] = {}
    for name, entry in (config.get("units") or {}).items():
        if not entry.get("enabled", True):
            continue
        cls = resolve(name)
        cfg: Mapping[str, Any] = dict(entry.get("cfg") or {})
        units[name] = (cls, cfg)
    return units


def main() -> int:
    # Load config FIRST so logging settings in YAML can shape where
    # supervisor.log is written and at what level.
    config = load_config()
    apply_logging_config(config.get("logging"))
    configure_supervisor_logging()

    service_cfg = config.get("service") or {}
    service_name = service_cfg.get("name", "service")
    log.info("starting %s", service_name)

    units = build_units(config)
    if not units:
        log.error("no units enabled in %s; exiting", CONFIG_PATH)
        return 1

    supervisor = Supervisor(units)
    supervisor.start()

    api_cfg = config.get("api") or {}
    app = build_app(
        supervisor,
        title=api_cfg.get("title") or f"{service_name} control",
        version=str(api_cfg.get("version", "0.1.0")),
    )
    server_config = uvicorn.Config(
        app,
        host=api_cfg.get("host", "127.0.0.1"),
        port=int(api_cfg.get("port", 8000)),
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(server_config)

    def _shutdown(signum: int, _frame) -> None:  # noqa: ANN001
        log.info("received signal %s", signum)
        server.should_exit = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.run()  # blocks until should_exit
    finally:
        supervisor.shutdown()
    return 0


if __name__ == "__main__":
    # ``spawn`` is required on Windows and keeps Linux/macOS behavior identical.
    mp.set_start_method("spawn", force=True)
    sys.exit(main())
