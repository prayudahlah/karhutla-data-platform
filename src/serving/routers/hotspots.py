"""Endpoint hotspot harian dan ringkasannya."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from serving.db import GoldStore
from serving.deps import get_store
from serving.queries import province_date_filters

router = APIRouter(prefix="/hotspots", tags=["hotspots"])

DAILY_COLUMNS = """
    province,
    date,
    hotspot_count,
    hotspot_kuat,
    hotspot_sedang,
    hotspot_lemah,
    hotspot_kandidat,
    active_cells,
    frp_sum,
    frp_mean,
    frp_max,
    freshness_at
"""


@router.get("/daily")
def hotspots_daily(
    province: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Jumlah hotspot per tier per provinsi per hari."""
    where, params = province_date_filters(province, start, end)
    rows = store.query(
        f"""
        select {DAILY_COLUMNS}
        from province_daily
        {where}
        order by date asc, province asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}


@router.get("/daily/total")
def hotspots_daily_total(
    province: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Total harian seluruh provinsi, dipakai grafik dashboard."""
    where, params = province_date_filters(province, start, end)
    rows = store.query(
        f"""
        select
            date,
            sum(hotspot_count) as hotspot_count,
            sum(hotspot_kuat) as hotspot_kuat,
            sum(hotspot_sedang) as hotspot_sedang,
            sum(hotspot_lemah) as hotspot_lemah,
            sum(hotspot_kandidat) as hotspot_kandidat,
            round(sum(frp_sum), 3) as frp_sum,
            max(frp_max) as frp_max
        from province_daily
        {where}
        group by date
        order by date asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}


@router.get("/summary")
def hotspots_summary(
    province: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Total hotspot per tier dan FRP untuk rentang tanggal."""
    where, params = province_date_filters(province, start, end)
    rows = store.query(
        f"""
        select
            province,
            sum(hotspot_count) as hotspot_count,
            sum(hotspot_kuat) as hotspot_kuat,
            sum(hotspot_sedang) as hotspot_sedang,
            sum(hotspot_lemah) as hotspot_lemah,
            sum(hotspot_kandidat) as hotspot_kandidat,
            sum(active_cells) as active_cell_days,
            round(sum(frp_sum), 3) as frp_sum,
            max(frp_max) as frp_max,
            min(date) as first_date,
            max(date) as last_date
        from province_daily
        {where}
        group by province
        order by hotspot_count desc, province asc
        """,
        params,
    )
    return {"count": len(rows), "rows": rows}
