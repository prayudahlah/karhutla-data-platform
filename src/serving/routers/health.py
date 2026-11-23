"""Endpoint kesehatan dan kesegaran data Gold."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from serving.db import GoldStore
from serving.deps import get_settings, get_store
from serving.settings import Settings

router = APIRouter(tags=["health"])


def _iceberg_status(settings: Settings) -> dict[str, Any]:
    """Status pointer Iceberg: kapan publish, snapshot, dan stale."""
    state_path = settings.iceberg_root / "publish_state.json"
    current_path = settings.iceberg_root / "current.json"
    published_at: str | None = None
    snapshots: dict[str, int] = {}

    if state_path.is_file():
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        published_at = payload.get("published_at")
    if current_path.is_file():
        payload = json.loads(current_path.read_text(encoding="utf-8"))
        published_at = published_at or payload.get("published_at")
        snapshots = payload.get("snapshots", {})

    if not published_at:
        return {"status": "missing", "stale": True, "snapshots": snapshots}

    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return {"status": "invalid", "stale": True, "snapshots": snapshots}
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - published).total_seconds() / 3600
    return {
        "status": "ok",
        "published_at": published_at,
        "age_hours": round(age_hours, 2),
        "stale": age_hours > 26,
        "snapshots": snapshots,
    }


@router.get("/health")
def health(
    store: GoldStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Status layanan, jumlah baris, freshness, dan pointer Iceberg."""
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
        "iceberg": _iceberg_status(settings),
    }
