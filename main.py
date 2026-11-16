from __future__ import annotations

import multiprocessing as mp
import signal
import sys
from pathlib import Path
from typing import Any, Mapping, Type

import uvicorn
import yaml

from api.control import build_app
from core import log
from core.base_unit import BaseUnit
from core.registry import resolve
from core.supervisor import DEFAULT_CHILD_UNIT_PREFIX, Supervisor

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config" / "settings.yaml"


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
    config = load_config()

    log_path = str((config.get("logging") or {}).get("path") or "").strip()
    if not log_path:
        print(f"logging.path is not set in {CONFIG_PATH}", file=sys.stderr)
        return 1
    # A relative path is taken from the app folder, not the current directory.
    log.init(APP_DIR / log_path, source="supervisor")

    service_cfg = config.get("service") or {}
    service_name = service_cfg.get("name", "service")
    log.info(f"starting {service_name}")

    units = build_units(config)
    if not units:
        log.error(f"no units enabled in {CONFIG_PATH}; exiting")
        return 1

    child_unit_prefix = str(
        service_cfg.get("child_unit_prefix") or DEFAULT_CHILD_UNIT_PREFIX
    ).strip()
    supervisor = Supervisor(units, child_unit_prefix=child_unit_prefix)
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

    received: list[int] = []

    def _shutdown(signum: int, _frame) -> None:  # noqa: ANN001
        # No logging here: the handler can interrupt a log write in this
        # same thread, and the write's lock is not re-entrant.
        received.append(signum)
        server.should_exit = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.run()  # blocks until should_exit
    finally:
        if received:
            log.info(f"received signal {received[0]}")
        supervisor.shutdown()
    return 0


if __name__ == "__main__":
    # ``spawn`` is required on Windows and keeps Linux/macOS behavior identical.
    mp.set_start_method("spawn", force=True)
    sys.exit(main())
