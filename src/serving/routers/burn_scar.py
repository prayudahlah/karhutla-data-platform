"""Endpoint luas terbakar (burn scar) bulanan dan kumulatif."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from serving.db import GoldStore
from serving.deps import get_store
from serving.queries import province_date_filters

router = APIRouter(prefix="/burn-scar", tags=["burn-scar"])


@router.get("/monthly")
def burn_scar_monthly(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    province: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Luas terbakar per provinsi per bulan (piksel dan km persegi)."""
    clauses: list[str] = []
    params: list[Any] = []
    if month:
        clauses.append("burn_month = ?")
        params.append(month)
    if province:
        clauses.append("province = ?")
        params.append(province)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = store.query(
        f"""
        select
            burn_month,
            province,
            scar_pixels,
            scar_area_km2,
            tile_count,
            qa_mean,
            uncertainty_mean,
            first_burn_date,
            last_burn_date
        from burn_scar_monthly
        {where}
        order by burn_month desc, scar_area_km2 desc, province asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}


@router.get("/cumulative")
def burn_scar_cumulative(
    province: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Luas terbakar kumulatif per provinsi per hari."""
    where, params = province_date_filters(province, start, end)
    rows = store.query(
        f"""
        select
            province,
            date,
            scar_pixels_cum,
            scar_area_km2_cum
        from province_daily
        {where}
        order by date asc, province asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}
