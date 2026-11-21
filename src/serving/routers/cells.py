"""Endpoint peta hotspot per sel grid 0,25 derajat."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from serving.db import GoldStore
from serving.deps import get_store

router = APIRouter(prefix="/cells", tags=["cells"])


@router.get("/hotspots")
def cells_hotspots(
    date_: date = Query(alias="date"),
    province: str | None = Query(default=None),
    min_hotspot: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    store: GoldStore = Depends(get_store),
) -> dict[str, Any]:
    """Sel grid yang punya hotspot pada satu tanggal, untuk peta dashboard."""
    clauses = ["date = ?", "hotspot_count >= ?"]
    params: list[Any] = [date_, min_hotspot]
    if province:
        clauses.append("province = ?")
        params.append(province)
    rows = store.query(
        f"""
        select
            cell_id,
            date,
            cell_lat,
            cell_lon,
            province,
            hotspot_count,
            hotspot_kuat,
            hotspot_sedang,
            hotspot_lemah,
            hotspot_kandidat,
            frp_sum,
            scar_area_km2_cum,
            weather_complete
        from cell_daily
        where {" and ".join(clauses)}
        order by hotspot_count desc, cell_id asc
        limit ?
        """,
        [*params, limit],
    )
    return {"count": len(rows), "rows": rows}
