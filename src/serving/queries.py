"""Pembantu query yang dipakai router serving."""

from __future__ import annotations

from datetime import date
from typing import Any

from serving.db import GoldStore


def province_date_filters(
    province: str | None,
    start: date | None,
    end: date | None,
) -> tuple[str, list[Any]]:
    """Bangun klausa WHERE untuk tabel province_daily."""
    clauses: list[str] = []
    params: list[Any] = []
    if province:
        clauses.append("province = ?")
        params.append(province)
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def rows(
    store: GoldStore,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    return store.query(sql, params)
