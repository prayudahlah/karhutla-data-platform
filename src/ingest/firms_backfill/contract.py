"""Kontrak event FIRMS untuk backfill.

Aturannya sama dengan ``stream/src/event_schema.py``. Kesamaannya diuji di
``tests/unit/test_firms_backfill_contract.py``; kalau salah satu berubah tanpa
yang lain, tes itu gagal.

Kunci dedup memuat satelit, jadi hotspot yang dilihat dua satelit tetap menjadi
dua event berbeda.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1

# Kolom CSV yang ikut dibawa apa adanya ke event, kalau ada.
RAW_FIELDS = (
    "confidence",
    "frp",
    "scan",
    "track",
    "daynight",
    "version",
    "bright_ti4",
    "bright_ti5",
    "brightness",
    "bright_t31",
    "instrument",
)


def make_key(row: Mapping[str, Any]) -> str:
    """Kunci dedup antar polling, sama seperti producer."""
    return (
        f"{row['latitude']}|{row['longitude']}|{row['acq_date']}|"
        f"{int(row['acq_time']):04d}|{row.get('satellite', '')}"
    )


def event_id_from_key(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()


def acquire_timestamp(acq_date: str, acq_time: Any) -> str:
    """Gabungkan tanggal dan jam akuisisi menjadi ISO UTC."""
    hour_minute = f"{int(acq_time):04d}"
    stamp = datetime.strptime(f"{acq_date} {hour_minute}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_event(
    row: Mapping[str, Any],
    *,
    source: str,
    ingested_at: str,
) -> dict[str, Any]:
    """Ubah satu baris CSV FIRMS menjadi event JSONL."""
    key = make_key(row)
    event: dict[str, Any] = {
        "event_id": event_id_from_key(key),
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "satellite": str(row.get("satellite") or ""),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "acq_date": str(row["acq_date"]),
        "acq_time": int(row["acq_time"]),
        "acq_ts_utc": acquire_timestamp(str(row["acq_date"]), row["acq_time"]),
        "ingested_at": ingested_at,
    }
    for field in RAW_FIELDS:
        value = row.get(field)
        if value in (None, ""):
            continue
        event[field] = value
    return event
