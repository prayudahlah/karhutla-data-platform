"""Endpoint kualitas udara harian per provinsi."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from serving.db import GoldStore
from serving.deps import get_store
from serving.queries import province_date_filters

router = APIRouter(prefix="/air-quality", tags=["air-quality"])


@router.get("/daily")
def air_quality_daily(
    province: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """PM2.5 harian per provinsi."""
    where, params = province_date_filters(province, start, end)
    rows = store.query(
        f"""
        select province, date, pm25_mean, pm25_max
        from province_daily
        {where}
        order by date asc, province asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}
