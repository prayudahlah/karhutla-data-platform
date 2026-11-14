from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from batch.silver.openmeteo import (
    DATASET_VARIABLES,
    _export_table,
    _write_quarantine,
    normalize_dataset,
    normalize_object,
    parse_bronze_object,
    write_normalized_dataset,
)


class FakeStore:
    def __init__(self, objects: dict[str, Any] | None = None) -> None:
        self.objects = objects or {}
        self.puts: dict[str, dict[str, Any]] = {}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def read_json(self, key: str) -> Any:
        return self.objects[key]

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        self.puts[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return key


def _key(
    dataset: str,
    *,
    run_id: str = "run-1",
    layout: str = "legacy",
    slug: str = "01_banda_aceh_aceh",
) -> str:
    if layout == "dataset":
        return (
            f"bronze/open_meteo/dataset={dataset}/ingest_date=2026-11-14"
            f"/run_id={run_id}/{slug}.json"
        )
    return (
        f"bronze/open_meteo/{dataset}/ingest_date=2026-11-14"
        f"/run_id={run_id}/{slug}.json"
    )


def _envelope(
    dataset: str,
    *,
    run_id: str = "run-1",
    city: str = "Banda Aceh",
    province: str = "Aceh",
    ingestion_timestamp: str = "2026-11-14T00:00:00Z",
    missing: str | None = None,
    bad_time: bool = False,
) -> dict[str, Any]:
    variables = DATASET_VARIABLES[dataset]
    times = [f"2026-11-14T{hour:02d}:00" for hour in range(24)]
    if bad_time:
        times[0] = "not-a-time"
    hourly: dict[str, Any] = {
        "time": times,
        **{variable: [float(hour) for hour in range(24)] for variable in variables},
    }
    if missing is not None:
        hourly.pop(missing)
    return {
        "dataset": dataset,
        "city": {
            "name": city,
            "province": province,
            "latitude": 5.5483,
            "longitude": 95.3238,
        },
        "run_id": run_id,
        "ingestion_timestamp": ingestion_timestamp,
        "record_count": 24,
        "response": {
            "utc_offset_seconds": 25200,
            "hourly_units": {variable: "unit" for variable in variables},
            "hourly": hourly,
        },
    }


def _normalize(
    store: FakeStore,
    dataset: str = "weather",
    *,
    allowed: set[tuple[str, str]] | None = None,
):
    return normalize_dataset(
        store,
        dataset,
        prefix="bronze/open_meteo",
        allowed_locations=allowed,
    )


def test_parse_bronze_object_supports_both_layouts() -> None:
    legacy = parse_bronze_object(
        _key("weather"),
        prefix="bronze/open_meteo",
        dataset="weather",
    )
    dataset = parse_bronze_object(
        _key("weather", layout="dataset"),
        prefix="bronze/open_meteo",
        dataset="weather",
    )

    assert legacy is not None and legacy.run_id == "run-1"
    assert legacy.ingest_date == date(2026, 11, 14)
    assert dataset is not None and dataset.key.endswith("run-1/01_banda_aceh_aceh.json")


def test_normalize_weather_converts_local_time_to_utc() -> None:
    store = FakeStore({_key("weather"): _envelope("weather")})
    result = normalize_object(
        store,
        parse_bronze_object(_key("weather"), prefix="bronze/open_meteo", dataset="weather"),
        allowed_locations={("aceh", "banda aceh")},
    )

    assert result.error is None
    assert len(result.rows) == 24
    assert result.rows[0]["ts_local"] == datetime(2026, 11, 14, 0, 0)
    assert result.rows[0]["ts_utc"] == datetime(2026, 11, 13, 17, 0)
    assert result.rows[0]["province"] == "Aceh"
    assert '"temperature_2m": "unit"' in result.rows[0]["units_json"]


def test_normalize_air_quality_uses_air_quality_variables() -> None:
    store = FakeStore({_key("air_quality"): _envelope("air_quality")})
    result = normalize_object(
        store,
        parse_bronze_object(
            _key("air_quality"),
            prefix="bronze/open_meteo",
            dataset="air_quality",
        ),
        allowed_locations=None,
    )

    assert result.error is None
    assert len(result.rows) == 24
    assert result.rows[0]["pm2_5"] == 0.0
    assert "temperature_2m" not in result.rows[0]


def test_normalize_skips_locations_outside_province_reference() -> None:
    store = FakeStore({_key("weather"): _envelope("weather")})
    result = _normalize(store, allowed={("papua", "jayapura")})

    assert result.objects_skipped == 1
    assert result.rows == []
    assert not result.passed


def test_normalize_quarantines_missing_variable() -> None:
    store = FakeStore({_key("weather"): _envelope("weather", missing="precipitation")})
    result = _normalize(store)

    assert result.objects_failed == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "missing_variables"
    assert not result.passed


def test_normalize_quarantines_invalid_time_per_row() -> None:
    store = FakeStore({_key("weather"): _envelope("weather", bad_time=True)})
    result = _normalize(store)

    assert len(result.rows) == 23
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "invalid_time"
    assert result.input_records == 24
    assert not result.passed


def test_normalize_reports_duplicates_without_removing_them() -> None:
    store = FakeStore(
        {
            _key("weather", run_id="run-1"): _envelope("weather", run_id="run-1"),
            _key("weather", run_id="run-2"): _envelope(
                "weather",
                run_id="run-2",
                ingestion_timestamp="2026-11-14T01:00:00Z",
            ),
        }
    )
    result = _normalize(store)

    assert result.objects_used == 2
    assert result.input_records == 48
    assert len(result.rows) == 48
    assert result.unique_rows == 24
    assert result.duplicate_rows == 24
    assert result.source_runs == ["run-1", "run-2"]
    assert result.passed


def test_write_normalized_dataset_writes_utc_partitions(tmp_path: Path) -> None:
    store = FakeStore({_key("weather"): _envelope("weather")})
    result = _normalize(store)
    keys = write_normalized_dataset(
        result,
        output_root=tmp_path,
        store=store,
        silver_run_id="silver-1",
        upload=True,
    )

    assert keys == [
        "silver/_normalized/open_meteo/dataset=weather/date=2026-11-13/part-00000.parquet",
        "silver/_normalized/open_meteo/dataset=weather/date=2026-11-14/part-00000.parquet",
    ]
    assert (tmp_path / keys[0].removeprefix("silver/")).is_file()
    assert store.puts[keys[0]]["metadata"]["kind"] == "silver-normalized"


def test_write_quarantine_writes_local_and_store(tmp_path: Path) -> None:
    store = FakeStore({_key("weather"): _envelope("weather", bad_time=True)})
    result = _normalize(store)
    keys = _write_quarantine(
        result,
        output_root=tmp_path,
        store=store,
        silver_run_id="silver-1",
        upload=True,
    )

    assert len(keys) == 1
    assert (tmp_path / keys[0].removeprefix("silver/")).is_file()
    assert store.puts[keys[0]]["metadata"]["kind"] == "silver-quarantine"


def test_export_table_writes_partitioned_parquet_and_dq(tmp_path: Path) -> None:
    db_path = tmp_path / "silver.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        create table open_meteo_weather (
            province varchar,
            city varchar,
            ts_utc timestamp,
            ts_local timestamp,
            run_id varchar,
            date date
        )
        """
    )
    connection.executemany(
        "insert into open_meteo_weather values (?, ?, ?, ?, ?, ?)",
        [
            (
                "Aceh",
                "Banda Aceh",
                datetime(2026, 11, 13, 17) + timedelta(hours=hour),
                datetime(2026, 11, 14, hour),
                "run-1",
                date(2026, 11, 14),
            )
            for hour in range(24)
        ],
    )
    connection.close()

    store = FakeStore()
    summary = _export_table(
        db_path,
        table_name="open_meteo_weather",
        source="open_meteo",
        dataset="weather",
        output_root=tmp_path,
        store=store,
        silver_run_id="silver-1",
        upload=True,
    )

    assert summary["rows"] == 24
    assert summary["partitions"] == {"2026-11-14": 24}
    assert summary["keys"] == [
        "silver/open_meteo/dataset=weather/date=2026-11-14/part-00000.parquet"
    ]
    assert (tmp_path / summary["keys"][0].removeprefix("silver/")).is_file()
    assert store.puts[summary["keys"][0]]["metadata"]["kind"] == "silver-final"
    assert summary["dq_key"].endswith("run_id=silver-1-final.json")
