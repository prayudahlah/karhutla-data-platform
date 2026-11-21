"""Aplikasi FastAPI read-only untuk tabel Gold.

Jalankan lokal::

    uvicorn serving.main:app --reload

Dokumentasi OpenAPI otomatis ada di ``/docs`` dan ``/openapi.json``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from serving.db import GoldStore, GoldUnavailable
from serving.routers import include_routers
from serving.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    store = GoldStore(resolved.gold_root, resolved.database_dsn)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        store.close()

    app = FastAPI(
        title=resolved.title,
        version=resolved.version,
        description=(
            "API read-only untuk Gold: hotspot, FRP, burn scar, cuaca, "
            "kualitas udara, dan peta sel grid. Panel prediksi menyusul ML."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.store = store
    include_routers(app)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # Checklist meminta 400 untuk parameter tanggal yang salah.
        return JSONResponse(
            status_code=400,
            content={"detail": "Parameter tidak valid", "errors": exc.errors()},
        )

    @app.exception_handler(GoldUnavailable)
    async def _gold_unavailable(
        _: Request,
        exc: GoldUnavailable,
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "service": resolved.title,
            "version": resolved.version,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()
