"""Daftar provinsi yang tersedia di Gold."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from serving.db import GoldStore
from serving.deps import get_store

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/provinces")
def list_provinces(store: GoldStore = Depends(get_store)) -> dict[str, Any]:
    """Provinsi yang muncul di province_daily, urut alfabet."""
    rows = store.query(
        "select distinct province from province_daily order by province"
    )
    return {"count": len(rows), "provinces": [row["province"] for row in rows]}
