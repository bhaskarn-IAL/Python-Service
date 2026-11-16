from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException

if TYPE_CHECKING:
    from core.supervisor import Supervisor


def build_app(supervisor: "Supervisor", title: str, version: str) -> FastAPI:
    app = FastAPI(title=title, version=version)

    @app.get("/health")
    def health() -> dict:
        statuses = supervisor.list_units()
        alive = sum(1 for s in statuses if s.alive)
        return {
            "status": "ok" if alive == len(statuses) and statuses else "degraded",
            "units_alive": alive,
            "units_total": len(statuses),
        }

    @app.get("/units")
    def units() -> dict:
        return {"units": [asdict(s) for s in supervisor.list_units()]}

    @app.post("/units/{name}/start")
    def start_unit(name: str) -> dict:
        if not supervisor.start_unit(name):
            raise HTTPException(status_code=404, detail=f"unknown unit: {name}")
        return {"ok": True, "unit": name, "action": "start"}

    @app.post("/units/{name}/stop")
    def stop_unit(name: str) -> dict:
        if not supervisor.stop_unit(name):
            raise HTTPException(status_code=404, detail=f"unknown unit: {name}")
        return {"ok": True, "unit": name, "action": "stop"}

    return app
