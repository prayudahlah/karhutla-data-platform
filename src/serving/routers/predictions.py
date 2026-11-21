"""Placeholder endpoint prediksi risiko.

Panel prediksi menunggu model ML (F-11/F-12). Endpoint sengaja mengembalikan
503 dengan pesan jelas supaya dashboard bisa menampilkan status "belum ada"
tanpa menebak-nebak.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/daily")
def predictions_daily(
    date: str | None = Query(default=None),
    province: str | None = Query(default=None),
) -> dict[str, Any]:
    raise HTTPException(
        status_code=503,
        detail=(
            "Prediksi risiko belum tersedia. Tabel risk_prediction_daily "
            "menunggu model ML (F-11/F-12)."
        ),
    )
