"""Endpoint kesehatan dan kesegaran data Gold."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from serving.db import GoldStore
from serving.deps import get_store

router = APIRouter(tags=["health"])


@router.get("/health")
def health(store: GoldStore = Depends(get_store)) -> dict[str, Any]:
    """Status layanan, jumlah baris, dan tanggal terbaru tiap tabel Gold."""
    row_counts = {
        table: int(store.query_one(f"select count(*) as n from {table}")["n"])  # type: ignore[index]
        for table in ("province_daily", "burn_scar_monthly", "cell_daily")
    }
    latest = store.query_one(
        """
        select
            max(date) as latest_date,
            max(freshness_at) as latest_ingest,
            count(distinct province) as province_count
        from province_daily
        """
    )
    return {
        "status": "ok",
        "row_counts": row_counts,
        "latest_date": latest["latest_date"] if latest else None,
        "latest_ingest": latest["latest_ingest"] if latest else None,
        "province_count": latest["province_count"] if latest else 0,
    }
