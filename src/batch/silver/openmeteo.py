"""Normalize Open-Meteo Bronze envelopes into Silver Parquet."""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc

from batch.silver.dq import (
    QUARANTINE_SCHEMA,
    DQCheck,
    DQReport,
    check_not_null,
    check_unique,
    utc_now_iso,
)
from batch.silver.parquet import table_from_rows, upload_parquet, write_parquet
from batch.silver.paths import (
    dq_report_key,
    manifest_key,
    normalized_key,
    quarantine_key,
    silver_key,
)
from common.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES, Settings
from common.storage import BronzeStore, ObjectNotFoundError
from ingest.openmeteo.locations import load_cities

logger = logging.getLogger(__name__)

SOURCE = "open_meteo"
DATASETS = ("weather", "air_quality")
DATASET_VARIABLES = {
    "weather": WEATHER_VARIABLES,
    "air_quality": AIR_QUALITY_VARIABLES,
}
BASE_FIELDS = [
    ("province", pa.string()),
    ("city", pa.string()),
    ("latitude", pa.float64()),
    ("longitude", pa.float64()),
    ("ts_utc", pa.timestamp("us")),
    ("ts_local", pa.timestamp("us")),
    ("run_id", pa.string()),
    ("ingestion_timestamp", pa.timestamp("us")),
    ("units_json", pa.string()),
]
SCHEMAS = {
    dataset: pa.schema(
        BASE_FIELDS + [(variable, pa.float64()) for variable in variables]
    )
    for dataset, variables in DATASET_VARIABLES.items()
}
TABLE_NAMES = {
    "weather": "open_meteo_weather",
    "air_quality": "open_meteo_air_quality",
}
LOCATION_LEVELS = ("province", "city", "all")


class OpenMeteoSilverError(RuntimeError):
    """Raised when Open-Meteo Silver cannot be built."""


@dataclass(frozen=True)
class BronzeObject:
    key: str
    dataset: str
    run_id: str
    ingest_date: date


@dataclass(frozen=True)
class RejectedRow:
    payload: dict[str, Any]
    reason: str
    date_value: date


@dataclass
class ObjectResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    record_count: int = 0
    run_id: str | None = None
    skipped: bool = False
    error: str | None = None


@dataclass
class DatasetResult:
    dataset: str
    rows: list[dict[str, Any]]
    rejected: list[RejectedRow]
    objects_total: int
    objects_used: int
    objects_skipped: int
    objects_failed: int
    input_records: int
    source_runs: list[str]
    units_missing: Counter[str]
    null_counts: Counter[str]
    unique_rows: int
    duplicate_rows: int
    locations: int
    timestamps: int
    checks: list[DQCheck]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


def new_silver_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def parse_bronze_object(key: str, *, prefix: str, dataset: str) -> BronzeObject | None:
    """Parse both legacy and dataset= Bronze layouts."""
    base = prefix.strip("/")
    if not key.startswith(f"{base}/"):
        return None
    parts = key[len(base) + 1 :].split("/")
    if len(parts) < 4:
        return None

    if parts[0] == dataset:
        ingest_part, run_part = parts[1], parts[2]
    elif parts[0] == f"dataset={dataset}":
        ingest_part, run_part = parts[1], parts[2]
    else:
        return None

    if not run_part.startswith("run_id="):
        return None
    if not parts[3].endswith(".json"):
        return None

    # Backfill menulis partisi period=YYYY-MM, sedangkan ingest harian memakai
    # ingest_date=YYYY-MM-DD. Keduanya diterima; period dipetakan ke hari pertama.
    try:
        if ingest_part.startswith("ingest_date="):
            ingest_date = date.fromisoformat(ingest_part.removeprefix("ingest_date="))
        elif ingest_part.startswith("period="):
            period = ingest_part.removeprefix("period=")
            ingest_date = date.fromisoformat(f"{period}-01")
        else:
            return None
    except ValueError:
        return None

    return BronzeObject(
        key=key,
        dataset=dataset,
        run_id=run_part.removeprefix("run_id="),
        ingest_date=ingest_date,
    )


def discover_bronze_objects(
    store: BronzeStore,
    dataset: str,
    *,
    prefix: str,
    run_id: str | None = None,
) -> list[BronzeObject]:
    base = prefix.strip("/")
    keys = [
        *store.list_keys(f"{base}/{dataset}/"),
        *store.list_keys(f"{base}/dataset={dataset}/"),
    ]
    objects: list[BronzeObject] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        parsed = parse_bronze_object(key, prefix=base, dataset=dataset)
        if parsed is None:
            continue
        if run_id is not None and parsed.run_id != run_id:
            continue
        objects.append(parsed)
    return sorted(objects, key=lambda item: (item.run_id, item.key))


def load_allowed_locations(settings: Settings, location_level: str) -> set[tuple[str, str]] | None:
    if location_level not in LOCATION_LEVELS:
        raise OpenMeteoSilverError(f"Unsupported location level: {location_level}")
    if location_level == "all":
        return None

    path = (
        settings.openmeteo.provinces_csv
        if location_level == "province"
        else settings.openmeteo.city_csv
    )
    cities = load_cities(path)
    return {(city.province.casefold(), city.name.casefold()) for city in cities}


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _parse_local_timestamp(value: Any, offset_seconds: int) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(seconds=offset_seconds)))
    return parsed


def _city_fields(envelope: Mapping[str, Any]) -> tuple[str, str, float, float] | None:
    city = envelope.get("city")
    if not isinstance(city, Mapping):
        return None
    province = city.get("province")
    name = city.get("name")
    latitude = city.get("latitude")
    longitude = city.get("longitude")
    if not isinstance(province, str) or not province.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return None
    return province.strip(), name.strip(), latitude_value, longitude_value


def _reject_all(
    *,
    envelope: Mapping[str, Any],
    obj: BronzeObject,
    reason: str,
) -> ObjectResult:
    return ObjectResult(
        rejected=[
            RejectedRow(
                payload={"key": obj.key, "reason": reason, "envelope": dict(envelope)},
                reason=reason,
                date_value=obj.ingest_date,
            )
        ],
        record_count=0,
        run_id=obj.run_id,
        error=reason,
    )


def normalize_object(
    store: BronzeStore,
    obj: BronzeObject,
    *,
    allowed_locations: set[tuple[str, str]] | None,
) -> ObjectResult:
    try:
        envelope = store.read_json(obj.key)
    except Exception as exc:  # noqa: BLE001 - report per-object failures in DQ
        return ObjectResult(
            rejected=[
                RejectedRow(
                    payload={"key": obj.key, "error": str(exc)},
                    reason="unreadable_object",
                    date_value=obj.ingest_date,
                )
            ],
            run_id=obj.run_id,
            error=f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(envelope, Mapping):
        return ObjectResult(
            rejected=[
                RejectedRow(
                    payload={"key": obj.key, "payload": envelope},
                    reason="invalid_envelope",
                    date_value=obj.ingest_date,
                )
            ],
            run_id=obj.run_id,
            error="invalid_envelope",
        )

    city_fields = _city_fields(envelope)
    if city_fields is None:
        return _reject_all(envelope=envelope, obj=obj, reason="invalid_city")
    province, city_name, latitude, longitude = city_fields

    if (
        allowed_locations is not None
        and (province.casefold(), city_name.casefold()) not in allowed_locations
    ):
        return ObjectResult(skipped=True, run_id=obj.run_id)

    if envelope.get("dataset") != obj.dataset:
        return _reject_all(envelope=envelope, obj=obj, reason="dataset_mismatch")

    response = envelope.get("response")
    if not isinstance(response, Mapping):
        return _reject_all(envelope=envelope, obj=obj, reason="missing_response")

    hourly = response.get("hourly")
    units = response.get("hourly_units")
    if not isinstance(hourly, Mapping):
        return _reject_all(envelope=envelope, obj=obj, reason="missing_hourly")
    if not isinstance(units, Mapping):
        return _reject_all(envelope=envelope, obj=obj, reason="missing_hourly_units")

    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        return _reject_all(envelope=envelope, obj=obj, reason="empty_hourly_time")

    variables = DATASET_VARIABLES[obj.dataset]
    missing_variables = [variable for variable in variables if variable not in hourly]
    if missing_variables:
        return _reject_all(envelope=envelope, obj=obj, reason="missing_variables")

    wrong_length = [
        variable
        for variable in variables
        if not isinstance(hourly[variable], list) or len(hourly[variable]) != len(times)
    ]
    if wrong_length:
        return _reject_all(envelope=envelope, obj=obj, reason="inconsistent_variable_lengths")

    offset = response.get("utc_offset_seconds")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        return _reject_all(envelope=envelope, obj=obj, reason="invalid_utc_offset")
    offset_seconds = int(offset)

    record_count = envelope.get("record_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int):
        record_count = len(times)
    if record_count != len(times):
        return _reject_all(envelope=envelope, obj=obj, reason="record_count_mismatch")

    ingestion_timestamp = _parse_utc_timestamp(envelope.get("ingestion_timestamp"))
    run_id = str(envelope.get("run_id") or obj.run_id)
    units_json = json.dumps(dict(units), ensure_ascii=False, sort_keys=True)

    rows: list[dict[str, Any]] = []
    rejected: list[RejectedRow] = []
    for index, raw_time in enumerate(times):
        local_dt = _parse_local_timestamp(raw_time, offset_seconds)
        if local_dt is None:
            rejected.append(
                RejectedRow(
                    payload={
                        "key": obj.key,
                        "city": city_name,
                        "province": province,
                        "time": raw_time,
                    },
                    reason="invalid_time",
                    date_value=obj.ingest_date,
                )
            )
            continue

        values: dict[str, float | None] = {}
        invalid_variables: list[str] = []
        for variable in variables:
            value = hourly[variable][index]
            if value is None:
                values[variable] = None
                continue
            try:
                values[variable] = float(value)
            except (TypeError, ValueError):
                invalid_variables.append(variable)

        if invalid_variables:
            rejected.append(
                RejectedRow(
                    payload={
                        "key": obj.key,
                        "city": city_name,
                        "province": province,
                        "time": raw_time,
                        "variables": invalid_variables,
                    },
                    reason="invalid_variable_value",
                    date_value=local_dt.date(),
                )
            )
            continue

        ts_utc = local_dt.astimezone(UTC).replace(tzinfo=None)
        rows.append(
            {
                "province": province,
                "city": city_name,
                "latitude": latitude,
                "longitude": longitude,
                "ts_utc": ts_utc,
                "ts_local": local_dt.replace(tzinfo=None),
                "run_id": run_id,
                "ingestion_timestamp": ingestion_timestamp,
                "units_json": units_json,
                **values,
            }
        )

    return ObjectResult(
        rows=rows,
        rejected=rejected,
        record_count=record_count,
        run_id=run_id,
    )


def _dataset_checks(
    *,
    dataset: str,
    result: DatasetResult,
    units_missing: Counter[str],
    local_dates: Counter[tuple[str, str, date]],
) -> list[DQCheck]:
    checks: list[DQCheck] = []
    checks.append(
        DQCheck(
            name="objects_loaded",
            passed=result.objects_failed == 0 and result.objects_used > 0,
            details={
                "objects_total": result.objects_total,
                "objects_used": result.objects_used,
                "objects_skipped": result.objects_skipped,
                "objects_failed": result.objects_failed,
            },
        )
    )
    checks.append(
        DQCheck(
            name="row_count_matches_bronze",
            passed=result.input_records == len(result.rows) + len(result.rejected),
            details={
                "input_records": result.input_records,
                "normalized_rows": len(result.rows),
                "rejected_rows": len(result.rejected),
            },
        )
    )
    checks.append(
        DQCheck(
            name="no_rejected_rows",
            passed=len(result.rejected) == 0,
            details={"rejected_rows": len(result.rejected)},
        )
    )
    checks.append(
        DQCheck(
            name="units_complete",
            passed=not units_missing,
            details={"missing": dict(units_missing)},
        )
    )
    incomplete = {
        f"{province}/{city}/{local_date.isoformat()}": count
        for (province, city, local_date), count in local_dates.items()
        if count != 24
    }
    checks.append(
        DQCheck(
            name="24h_completeness",
            passed=not incomplete,
            details={
                "location_days": len(local_dates),
                "incomplete": incomplete,
            },
        )
    )
    checks.append(
        DQCheck(
            name="duplicates_reported",
            passed=True,
            details={
                "unique_rows": result.unique_rows,
                "duplicate_rows": result.duplicate_rows,
                "note": "Duplikat sah; dedup dilakukan di dbt.",
            },
        )
    )
    checks.append(
        DQCheck(
            name="dataset_non_empty",
            passed=bool(result.rows),
            details={"dataset": dataset, "rows": len(result.rows)},
        )
    )
    return checks


def normalize_dataset(
    store: BronzeStore,
    dataset: str,
    *,
    prefix: str,
    allowed_locations: set[tuple[str, str]] | None,
    run_id: str | None = None,
) -> DatasetResult:
    objects = discover_bronze_objects(store, dataset, prefix=prefix, run_id=run_id)
    rows: list[dict[str, Any]] = []
    rejected: list[RejectedRow] = []
    source_runs: set[str] = set()
    units_missing: Counter[str] = Counter()
    null_counts: Counter[str] = Counter()
    input_records = 0
    objects_used = 0
    objects_skipped = 0
    objects_failed = 0

    for obj in objects:
        result = normalize_object(store, obj, allowed_locations=allowed_locations)
        if result.skipped:
            objects_skipped += 1
            continue
        if result.error is not None and not result.rows:
            objects_failed += 1
        else:
            objects_used += 1
            input_records += result.record_count
            if result.run_id:
                source_runs.add(result.run_id)
        rows.extend(result.rows)
        rejected.extend(result.rejected)

        if not result.rejected and result.rows:
            units = json.loads(result.rows[0]["units_json"])
            for variable in DATASET_VARIABLES[dataset]:
                if variable not in units:
                    units_missing[variable] += 1

    variables = DATASET_VARIABLES[dataset]
    for row in rows:
        for variable in variables:
            if row[variable] is None:
                null_counts[variable] += 1

    keys = [(row["province"], row["city"], row["ts_utc"]) for row in rows]
    unique_rows = len(set(keys))
    local_dates: Counter[tuple[str, str, date]] = Counter()
    seen_keys: set[tuple[str, str, datetime]] = set()
    for row, key in zip(rows, keys, strict=True):
        if key in seen_keys:
            continue
        seen_keys.add(key)
        local_dates[(row["province"], row["city"], row["ts_local"].date())] += 1

    result = DatasetResult(
        dataset=dataset,
        rows=rows,
        rejected=rejected,
        objects_total=len(objects),
        objects_used=objects_used,
        objects_skipped=objects_skipped,
        objects_failed=objects_failed,
        input_records=input_records,
        source_runs=sorted(source_runs),
        units_missing=units_missing,
        null_counts=null_counts,
        unique_rows=unique_rows,
        duplicate_rows=len(rows) - unique_rows,
        locations=len({(row["province"], row["city"]) for row in rows}),
        timestamps=len({row["ts_utc"] for row in rows}),
        checks=[],
    )
    result.checks = _dataset_checks(
        dataset=dataset,
        result=result,
        units_missing=units_missing,
        local_dates=local_dates,
    )
    return result


def _local_path(root: Path, key: str) -> Path:
    return root / key.removeprefix("silver/")


def _write_json_local(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_quarantine(
    result: DatasetResult,
    *,
    output_root: Path,
    store: BronzeStore,
    silver_run_id: str,
    upload: bool,
) -> list[str]:
    if not result.rejected:
        return []

    by_date: dict[date, list[RejectedRow]] = defaultdict(list)
    for rejected in result.rejected:
        by_date[rejected.date_value].append(rejected)

    keys: list[str] = []
    for date_value, rejected_rows in sorted(by_date.items()):
        payloads = [
            {
                "source": SOURCE,
                "dataset": result.dataset,
                "run_id": silver_run_id,
                "reason": rejected.reason,
                "payload": json.dumps(rejected.payload, ensure_ascii=False, default=str),
                "quarantined_at": utc_now_iso(),
            }
            for rejected in rejected_rows
        ]
        table = table_from_rows(payloads, schema=QUARANTINE_SCHEMA)
        key = quarantine_key(SOURCE, result.dataset, date_value)
        local_path = _local_path(output_root, key)
        write_parquet(local_path, table)
        if upload:
            upload_parquet(
                store,
                key,
                table,
                metadata={
                    "kind": "silver-quarantine",
                    "source": SOURCE,
                    "dataset": result.dataset,
                    "run-id": silver_run_id,
                },
                overwrite=True,
            )
        keys.append(key)
    return keys


def write_normalized_dataset(
    result: DatasetResult,
    *,
    output_root: Path,
    store: BronzeStore,
    silver_run_id: str,
    upload: bool,
) -> list[str]:
    if not result.rows:
        return []

    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in result.rows:
        by_date[row["ts_utc"].date()].append(row)

    keys: list[str] = []
    for date_value, rows in sorted(by_date.items()):
        table = table_from_rows(rows, schema=SCHEMAS[result.dataset])
        key = normalized_key(SOURCE, result.dataset, date_value)
        local_path = _local_path(output_root, key)
        write_parquet(local_path, table)
        if upload:
            upload_parquet(
                store,
                key,
                table,
                metadata={
                    "kind": "silver-normalized",
                    "source": SOURCE,
                    "dataset": result.dataset,
                    "run-id": silver_run_id,
                    "rows": str(table.num_rows),
                },
                overwrite=True,
            )
        keys.append(key)
    return keys


def _build_dq_report(
    result: DatasetResult,
    *,
    silver_run_id: str,
    normalized_keys: Sequence[str],
    quarantine_keys: Sequence[str],
) -> DQReport:
    report = DQReport(source=SOURCE, dataset=result.dataset, run_id=silver_run_id)
    report.input_rows = result.input_records
    report.accepted_rows = len(result.rows)
    report.rejected_rows = len(result.rejected)
    report.duplicate_rows = result.duplicate_rows
    report.checks.extend(result.checks)
    report.checks.append(
        DQCheck(
            name="normalized_outputs",
            passed=bool(normalized_keys),
            details={
                "keys": list(normalized_keys),
                "rows": len(result.rows),
                "locations": result.locations,
                "timestamps": result.timestamps,
                "source_runs": result.source_runs,
                "objects_skipped": result.objects_skipped,
                "null_counts": dict(result.null_counts),
            },
        )
    )
    report.checks.append(
        DQCheck(
            name="quarantine_outputs",
            passed=True,
            details={"keys": list(quarantine_keys), "rows": len(result.rejected)},
        )
    )
    return report


def normalize_all(
    settings: Settings,
    store: BronzeStore,
    *,
    datasets: Sequence[str] = DATASETS,
    location_level: str = "province",
    bronze_run_id: str | None = None,
    output_root: Path = Path("data/silver"),
    upload: bool = True,
    silver_run_id: str | None = None,
) -> dict[str, Any]:
    silver_run_id = silver_run_id or new_silver_run_id()
    allowed_locations = load_allowed_locations(settings, location_level)
    started_at = utc_now_iso()
    dataset_summaries: dict[str, Any] = {}
    dq_keys: list[str] = []

    for dataset in datasets:
        if dataset not in DATASETS:
            raise OpenMeteoSilverError(f"Unsupported dataset: {dataset}")
        result = normalize_dataset(
            store,
            dataset,
            prefix=settings.garage.prefix,
            allowed_locations=allowed_locations,
            run_id=bronze_run_id,
        )
        normalized_keys = write_normalized_dataset(
            result,
            output_root=output_root,
            store=store,
            silver_run_id=silver_run_id,
            upload=upload,
        )
        quarantine_keys = _write_quarantine(
            result,
            output_root=output_root,
            store=store,
            silver_run_id=silver_run_id,
            upload=upload,
        )
        report = _build_dq_report(
            result,
            silver_run_id=silver_run_id,
            normalized_keys=normalized_keys,
            quarantine_keys=quarantine_keys,
        )
        dq_key = dq_report_key(SOURCE, dataset, silver_run_id)
        if upload:
            report.write(store, dq_key, overwrite=True)
        _write_json_local(_local_path(output_root, dq_key), report.as_dict())
        dq_keys.append(dq_key)
        dataset_summaries[dataset] = {
            "status": report.status,
            "objects_total": result.objects_total,
            "objects_used": result.objects_used,
            "objects_skipped": result.objects_skipped,
            "objects_failed": result.objects_failed,
            "input_records": result.input_records,
            "normalized_rows": len(result.rows),
            "rejected_rows": len(result.rejected),
            "duplicate_rows": result.duplicate_rows,
            "unique_rows": result.unique_rows,
            "locations": result.locations,
            "timestamps": result.timestamps,
            "source_runs": result.source_runs,
            "normalized_keys": normalized_keys,
            "quarantine_keys": quarantine_keys,
            "dq_key": dq_key,
        }

    finished_at = utc_now_iso()
    manifest = {
        "schema_version": 1,
        "source": SOURCE,
        "run_id": silver_run_id,
        "status": (
            "success"
            if all(item["status"] == "passed" for item in dataset_summaries.values())
            else "failed"
        ),
        "started_at": started_at,
        "finished_at": finished_at,
        "location_level": location_level,
        "datasets": dataset_summaries,
        "dq_reports": dq_keys,
    }
    key = manifest_key(silver_run_id)
    if upload:
        store.put_json(key, manifest, overwrite=True)
    _write_json_local(_local_path(output_root, key), manifest)
    return manifest


def _validate_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise OpenMeteoSilverError(f"Unsafe table name: {value!r}")
    return value


def _export_table(
    db_path: Path,
    *,
    table_name: str,
    source: str,
    dataset: str,
    output_root: Path,
    store: BronzeStore,
    silver_run_id: str,
    upload: bool,
) -> dict[str, Any]:
    table_name = _validate_identifier(table_name)
    if not db_path.is_file():
        raise OpenMeteoSilverError(f"dbt database not found: {db_path}")

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        table = connection.sql(f'select * from "{table_name}"').to_arrow_table()
    finally:
        connection.close()

    if table.num_rows == 0:
        raise OpenMeteoSilverError(f"dbt table is empty: {table_name}")
    if "date" not in table.column_names:
        raise OpenMeteoSilverError(f"dbt table has no date column: {table_name}")

    date_field = table.schema.field("date")
    date_values = sorted(set(table.column("date").to_pylist()))
    partitions: dict[str, int] = {}
    keys: list[str] = []
    for date_value in date_values:
        mask = pc.equal(table.column("date"), pa.scalar(date_value, type=date_field.type))
        partition = table.filter(mask)
        partitions[date_value.isoformat()] = partition.num_rows
        key = silver_key(source, dataset, date_value)
        local_path = _local_path(output_root, key)
        write_parquet(local_path, partition)
        if upload:
            upload_parquet(
                store,
                key,
                partition,
                metadata={
                    "kind": "silver-final",
                    "source": source,
                    "dataset": dataset,
                    "run-id": silver_run_id,
                    "rows": str(partition.num_rows),
                },
                overwrite=True,
            )
        keys.append(key)

    rows = table.to_pylist()
    key_rows = [(row["province"], row["city"], row["ts_utc"]) for row in rows]
    local_dates = Counter(
        (row["province"], row["city"], row["ts_local"].date()) for row in rows
    )
    incomplete = {
        f"{province}/{city}/{local_date.isoformat()}": count
        for (province, city, local_date), count in local_dates.items()
        if count != 24
    }
    checks = [
        check_unique("unique_key", key_rows),
        check_not_null(
            "not_null_keys",
            rows,
            ["province", "city", "ts_utc", "ts_local", "run_id"],
        ),
        DQCheck(
            name="24h_completeness",
            passed=not incomplete,
            details={"location_days": len(local_dates), "incomplete": incomplete},
        ),
        DQCheck(
            name="partitions",
            passed=bool(partitions),
            details={"counts": partitions},
        ),
    ]
    report = DQReport(source=source, dataset=dataset, run_id=f"{silver_run_id}-final")
    report.input_rows = table.num_rows
    report.accepted_rows = table.num_rows
    report.rejected_rows = 0
    report.duplicate_rows = 0
    report.checks.extend(checks)
    report_key = dq_report_key(source, dataset, f"{silver_run_id}-final")
    if upload:
        report.write(store, report_key, overwrite=True)
    _write_json_local(_local_path(output_root, report_key), report.as_dict())

    return {
        "table": table_name,
        "rows": table.num_rows,
        "partitions": partitions,
        "keys": keys,
        "dq_key": report_key,
        "status": report.status,
    }


def export_all(
    store: BronzeStore,
    *,
    db_path: Path = Path("data/silver.duckdb"),
    output_root: Path = Path("data/silver"),
    silver_run_id: str,
    upload: bool = True,
    expected_rows: int | None = None,
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for dataset in DATASETS:
        summary = _export_table(
            db_path,
            table_name=TABLE_NAMES[dataset],
            source=SOURCE,
            dataset=dataset,
            output_root=output_root,
            store=store,
            silver_run_id=silver_run_id,
            upload=upload,
        )
        if expected_rows is not None and summary["rows"] != expected_rows:
            raise OpenMeteoSilverError(
                f"{dataset} row count {summary['rows']} != expected {expected_rows}"
            )
        summaries[dataset] = summary

    key = manifest_key(silver_run_id)
    manifest: dict[str, Any]
    manifest_path = _local_path(output_root, key)
    if upload:
        try:
            manifest = store.read_json(key)
        except ObjectNotFoundError:
            manifest = {
                "schema_version": 1,
                "source": SOURCE,
                "run_id": silver_run_id,
            }
    elif manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": 1,
            "source": SOURCE,
            "run_id": silver_run_id,
        }
    manifest["final"] = summaries
    manifest["final_finished_at"] = utc_now_iso()
    if upload:
        store.put_json(key, manifest, overwrite=True)
    _write_json_local(manifest_path, manifest)
    return manifest


def _print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize", help="Bronze JSON -> normalized Parquet")
    normalize_parser.add_argument(
        "--location-level",
        choices=LOCATION_LEVELS,
        default="province",
    )
    normalize_parser.add_argument("--run-id", help="Batasi ke satu run_id Bronze")
    normalize_parser.add_argument(
        "--dataset",
        action="append",
        choices=DATASETS,
        help="Dataset yang diproses; boleh diulang.",
    )
    normalize_parser.add_argument("--output-root", type=Path, default=Path("data/silver"))
    normalize_parser.add_argument("--silver-run-id")
    normalize_parser.add_argument("--no-upload", action="store_true")

    export_parser = subparsers.add_parser("export", help="dbt table -> final Silver Parquet")
    export_parser.add_argument("--db", type=Path, default=Path("data/silver.duckdb"))
    export_parser.add_argument("--output-root", type=Path, default=Path("data/silver"))
    export_parser.add_argument("--silver-run-id", required=True)
    export_parser.add_argument("--expected-rows", type=int)
    export_parser.add_argument("--no-upload", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)

    if args.command == "normalize":
        datasets = tuple(args.dataset) if args.dataset else DATASETS
        manifest = normalize_all(
            settings,
            store,
            datasets=datasets,
            location_level=args.location_level,
            bronze_run_id=args.run_id,
            output_root=args.output_root,
            upload=not args.no_upload,
            silver_run_id=args.silver_run_id,
        )
        _print(
            {
                "run_id": manifest["run_id"],
                "status": manifest["status"],
                "location_level": manifest["location_level"],
                "datasets": manifest["datasets"],
            }
        )
        return 0 if manifest["status"] == "success" else 1

    manifest = export_all(
        store,
        db_path=args.db,
        output_root=args.output_root,
        silver_run_id=args.silver_run_id,
        upload=not args.no_upload,
        expected_rows=args.expected_rows,
    )
    _print({"run_id": manifest["run_id"], "final": manifest["final"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
