"""Normalisasi event FIRMS: JSONL di Bronze menjadi Parquet di Silver.

Modul ini hanya mengetikkan data. Deduplikasi ``event_id`` sengaja tidak
dilakukan di sini: sesuai keputusan di docs/roadmap-silver.md, dedup dikerjakan
di SQL setelah semua sumber tersedia. Karena itu tabel hasil di lapisan
``_normalized`` masih boleh memuat event berulang, dan laporan DQ mencatat
berapa banyak.

Keluaran:

- ``silver/_normalized/firms/dataset=hotspot/date=<acq_date>/part-00000.parquet``
- ``silver/_dq/firms/dataset=hotspot/run_id=<run_id>.json``
- ``silver/_quarantine/firms/dataset=hotspot/date=<ingest_date>/part-00000.parquet``
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa

from batch.silver.dq import DQReport, check_not_null, write_quarantine
from batch.silver.parquet import ObjectStore, table_from_rows
from batch.silver.paths import dq_report_key, normalized_key, quarantine_key
from batch.silver.sync import publish_table
from common.config import Settings
from common.run import new_run_id
from common.storage import BronzeStore

SOURCE = "firms"
DATASET = "hotspot"
BRONZE_DATASET = "hotspot"

JAKARTA = ZoneInfo("Asia/Jakarta")

# Salinan dari stream/src/event_schema.py. Tidak diimpor langsung supaya modul
# batch tidak bergantung pada layout node stream.
REQUIRED_FIELDS = (
    "event_id",
    "source",
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "satellite",
    "acq_ts_utc",
    "ingested_at",
)

REJECT_INVALID_JSON = "invalid_json"
REJECT_MISSING_FIELDS = "missing_fields"
REJECT_BAD_TIMESTAMP = "bad_timestamp"
REJECT_BAD_COORDINATE = "bad_coordinate"

FIRMS_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("source", pa.string()),
        ("satellite", pa.string()),
        ("instrument", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("acq_ts_utc", pa.timestamp("us")),
        ("acq_ts_local", pa.timestamp("us")),
        ("acq_date", pa.date32()),
        ("acq_time", pa.string()),
        ("confidence", pa.string()),
        ("confidence_score", pa.int16()),
        ("frp", pa.float64()),
        ("brightness", pa.float64()),
        ("brightness_secondary", pa.float64()),
        ("scan", pa.float64()),
        ("track", pa.float64()),
        ("daynight", pa.string()),
        ("version", pa.string()),
        ("ingested_at", pa.timestamp("us")),
        ("in_bbox", pa.bool_()),
        ("source_file", pa.string()),
    ]
)


class FirmsSilverError(RuntimeError):
    """Bronze FIRMS kosong atau tidak bisa diurai."""


class FirmsEventError(ValueError):
    """Satu baris event tidak lolos validasi."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


_INGEST_DATE = re.compile(r"ingest_date=(\d{4}-\d{2}-\d{2})")


def parse_timestamp(value: Any) -> datetime:
    """Terima ISO 8601 dengan Z, offset, atau tanpa zona (dianggap UTC)."""
    if not isinstance(value, str) or not value.strip():
        raise FirmsEventError(REJECT_BAD_TIMESTAMP, f"timestamp tidak valid: {value!r}")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FirmsEventError(REJECT_BAD_TIMESTAMP, f"timestamp tidak valid: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_acq_time(value: Any) -> str:
    """acq_time bisa datang sebagai int 712 atau string '0712'."""
    if isinstance(value, bool):
        raise FirmsEventError(REJECT_MISSING_FIELDS, f"acq_time tidak valid: {value!r}")
    if isinstance(value, int):
        return f"{value:04d}"
    text = str(value).strip()
    if not text.isdigit():
        raise FirmsEventError(REJECT_MISSING_FIELDS, f"acq_time tidak valid: {value!r}")
    return text.zfill(4)


def _first_present(event: dict[str, Any], *names: str) -> Any:
    """Ambil nilai pertama yang tidak None. MODIS dan VIIRS memakai nama beda."""
    for name in names:
        value = event.get(name)
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence_values(value: Any) -> tuple[str, int | None]:
    """Pisahkan label dan skor. MODIS memberi angka, VIIRS memberi label."""
    if isinstance(value, bool):
        return str(value), None
    if isinstance(value, (int, float)):
        score = int(value)
        return str(score), score
    text = str(value).strip()
    if text.isdigit():
        return text, int(text)
    return text.lower(), None


def in_bbox(latitude: float, longitude: float, bbox: tuple[float, ...]) -> bool:
    west, south, east, north = bbox
    return west <= longitude <= east and south <= latitude <= north


def parse_event(
    raw: str,
    *,
    source_file: str,
    bbox: tuple[float, ...],
) -> dict[str, Any]:
    """Ubah satu baris JSONL menjadi satu baris Parquet."""
    stripped = raw.strip()
    if not stripped:
        raise FirmsEventError(REJECT_INVALID_JSON, "baris kosong")

    try:
        event = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise FirmsEventError(REJECT_INVALID_JSON, str(exc)) from exc
    if not isinstance(event, dict):
        raise FirmsEventError(REJECT_INVALID_JSON, "bukan objek JSON")

    missing = [name for name in REQUIRED_FIELDS if event.get(name) in (None, "")]
    if missing:
        raise FirmsEventError(REJECT_MISSING_FIELDS, "field kosong: " + ", ".join(missing))

    try:
        latitude = float(event["latitude"])
        longitude = float(event["longitude"])
    except (TypeError, ValueError) as exc:
        raise FirmsEventError(REJECT_BAD_COORDINATE, "koordinat bukan angka") from exc

    acquired = parse_timestamp(event["acq_ts_utc"])
    ingested = parse_timestamp(event["ingested_at"])

    try:
        acq_date = date.fromisoformat(str(event["acq_date"]).strip())
    except ValueError as exc:
        raise FirmsEventError(
            REJECT_BAD_TIMESTAMP, f"acq_date tidak valid: {event.get('acq_date')!r}"
        ) from exc

    confidence, confidence_score = _confidence_values(event.get("confidence"))

    return {
        "event_id": str(event["event_id"]),
        "source": str(event["source"]),
        "satellite": str(event["satellite"]),
        "instrument": str(event.get("instrument") or "") or None,
        "latitude": latitude,
        "longitude": longitude,
        "acq_ts_utc": acquired.replace(tzinfo=None),
        "acq_ts_local": acquired.astimezone(JAKARTA).replace(tzinfo=None),
        "acq_date": acq_date,
        "acq_time": parse_acq_time(event["acq_time"]),
        "confidence": confidence,
        "confidence_score": confidence_score,
        "frp": _float_or_none(event.get("frp")),
        "brightness": _float_or_none(_first_present(event, "bright_ti4", "brightness")),
        "brightness_secondary": _float_or_none(_first_present(event, "bright_ti5", "bright_t31")),
        "scan": _float_or_none(event.get("scan")),
        "track": _float_or_none(event.get("track")),
        "daynight": str(event.get("daynight") or "") or None,
        "version": str(event.get("version") or "") or None,
        "ingested_at": ingested.replace(tzinfo=None),
        "in_bbox": in_bbox(latitude, longitude, bbox),
        "source_file": source_file,
    }


def ingest_date_from_key(key: str) -> date | None:
    match = _INGEST_DATE.search(key)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_jsonl(
    payload: bytes,
    *,
    source_file: str,
    bbox: tuple[float, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Kembalikan (baris valid, baris karantina) dari satu objek Bronze."""
    text = payload.decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(parse_event(line, source_file=source_file, bbox=bbox))
        except FirmsEventError as exc:
            rejected.append(
                {
                    "source_file": source_file,
                    "line": number,
                    "reason": exc.reason,
                    "message": str(exc),
                    "payload": line[:2000],
                }
            )
    return rows, rejected


def normalize(
    store: ObjectStore,
    settings: Settings,
    *,
    run_id: str,
    local_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Urai seluruh objek Bronze FIRMS menjadi Parquet Silver."""
    prefix = f"{settings.firms_bronze.prefix}/dataset={BRONZE_DATASET}"
    keys = sorted(key for key in store.list_keys(prefix) if key.endswith(".jsonl"))
    if not keys:
        raise FirmsSilverError(
            f"Tidak ada objek JSONL di {prefix}; pastikan consumer sudah menulis Bronze"
        )

    rows_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    rejected_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    total_lines = 0
    total_rejected = 0
    fallback_date = date.today()

    for key in keys:
        rows, rejected = parse_jsonl(
            store.read_bytes(key), source_file=key, bbox=settings.burned_area.bbox
        )
        total_lines += len(rows) + len(rejected)
        total_rejected += len(rejected)
        for row in rows:
            rows_by_date[row["acq_date"]].append(row)
        if rejected:
            bucket = ingest_date_from_key(key) or fallback_date
            rejected_by_date[bucket].extend(rejected)

    written = 0
    for acq_date in sorted(rows_by_date):
        publish_table(
            store,
            normalized_key(SOURCE, DATASET, acq_date),
            table_from_rows(rows_by_date[acq_date], schema=FIRMS_SCHEMA),
            local_root=local_root,
            metadata={"run-id": run_id, "source": SOURCE, "dataset": DATASET},
            overwrite=overwrite,
        )
        written += len(rows_by_date[acq_date])

    for ingest_date, rejected in sorted(rejected_by_date.items()):
        write_quarantine(
            store,
            quarantine_key(SOURCE, DATASET, ingest_date),
            rejected,
            source=SOURCE,
            dataset=DATASET,
            reason="invalid_event",
            run_id=run_id,
            overwrite=overwrite,
        )

    all_rows = [row for rows in rows_by_date.values() for row in rows]
    duplicates = _duplicate_events(all_rows)
    duplicate_ratio = duplicates / written if written else 0.0
    inside = sum(1 for row in all_rows if row["in_bbox"])
    inside_ratio = inside / written if written else 0.0

    report = DQReport(source=SOURCE, dataset=DATASET, run_id=run_id)
    report.input_rows = total_lines
    report.accepted_rows = written
    report.rejected_rows = total_rejected
    report.duplicate_rows = duplicates
    report.add_check(
        "rows_balanced",
        passed=total_lines == written + total_rejected,
        input_rows=total_lines,
        accepted_rows=written,
        rejected_rows=total_rejected,
    )
    report.checks.append(
        check_not_null(
            "keys_not_null",
            all_rows,
            ["event_id", "acq_ts_utc", "latitude", "longitude"],
        )
    )
    report.add_check(
        "duplicate_ratio",
        passed=duplicate_ratio <= 0.10,
        duplicates=duplicates,
        accepted_rows=written,
        ratio=round(duplicate_ratio, 4),
    )
    report.add_check(
        "in_bbox_ratio",
        passed=inside_ratio >= 0.95,
        inside=inside,
        accepted_rows=written,
        ratio=round(inside_ratio, 4),
    )
    dq_key = dq_report_key(SOURCE, DATASET, run_id)
    report.write(store, dq_key, overwrite=overwrite)

    return {
        "bronze_objects": len(keys),
        "dates": len(rows_by_date),
        "rows_written": written,
        "rows_quarantined": total_rejected,
        "duplicate_event_ids": duplicates,
        "dq_report_key": dq_key,
        "dq_status": report.status,
    }


def _duplicate_events(rows: list[dict[str, Any]]) -> int:
    counts = Counter(row["event_id"] for row in rows)
    return sum(count - 1 for count in counts.values() if count > 1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalisasi FIRMS Bronze ke Silver")
    sub = parser.add_subparsers(dest="command", required=True)

    normalize_parser = sub.add_parser("normalize", help="JSONL Bronze -> parquet")
    normalize_parser.add_argument("--run-id", default=None, help="Default dibuat otomatis")
    normalize_parser.add_argument(
        "--local-root",
        type=Path,
        default=Path("data/silver/_normalized"),
        help="salinan lokal untuk dbt",
    )
    normalize_parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="jangan menulis salinan lokal, cukup ke Garage",
    )

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)
    result = normalize(
        store,
        settings,
        run_id=args.run_id or new_run_id(),
        local_root=None if args.no_mirror else args.local_root,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
