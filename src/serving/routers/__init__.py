"""Kumpulan router serving."""

from __future__ import annotations

from fastapi import FastAPI

from serving.routers import (
    air_quality,
    burn_scar,
    cells,
    frp,
    health,
    hotspots,
    meta,
    predictions,
    weather,
)

MODULES = (
    health,
    meta,
    hotspots,
    frp,
    burn_scar,
    weather,
    air_quality,
    cells,
    predictions,
)


def include_routers(app: FastAPI) -> None:
    for module in MODULES:
        app.include_router(module.router)
