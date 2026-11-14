from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from batch.silver.paths import (
    SilverPathError,
    dq_report_key,
    manifest_key,
    normalized_key,
    normalized_prefix,
    partition_date,
    quarantine_key,
    silver_key,
    silver_prefix,
)


def test_normalized_key_uses_source_dataset_and_date() -> None:
    assert normalized_key("open_meteo", "weather", "2026-11-14") == (
        "silver/_normalized/open_meteo/dataset=weather/date=2026-11-14/part-00000.parquet"
    )


def test_silver_key_supports_part_number() -> None:
    assert silver_key("firms", "hotspot", date(2026, 11, 14), part=3) == (
        "silver/firms/dataset=hotspot/date=2026-11-14/part-00003.parquet"
    )


def test_prefixes_are_distinct() -> None:
    assert normalized_prefix("open_meteo", "air_quality", "2026-11-14") != silver_prefix(
        "open_meteo", "air_quality", "2026-11-14"
    )
    assert quarantine_key("open_meteo", "weather", "2026-11-14") == (
        "silver/_quarantine/open_meteo/dataset=weather/date=2026-11-14/part-00000.parquet"
    )


def test_partition_date_accepts_datetime_and_utc_date() -> None:
    moment = datetime(2026, 11, 14, 23, 30, tzinfo=UTC)
    assert partition_date(moment) == "2026-11-14"


def test_dq_and_manifest_keys() -> None:
    assert dq_report_key("open_meteo", "weather", "run-1") == (
        "silver/_dq/open_meteo/dataset=weather/run_id=run-1.json"
    )
    assert manifest_key("20261114T054850Z-96a36e12") == (
        "silver/manifests/run_id=20261114T054850Z-96a36e12.json"
    )


@pytest.mark.parametrize("source", ["Open-Meteo", "../escape", "", "open meteo"])
def test_rejects_unsafe_source(source: str) -> None:
    with pytest.raises(SilverPathError):
        normalized_prefix(source, "weather", "2026-11-14")


@pytest.mark.parametrize("date_value", ["2026-13-01", "14-11-2026", "not-a-date"])
def test_rejects_invalid_date(date_value: str) -> None:
    with pytest.raises(SilverPathError):
        partition_date(date_value)


def test_rejects_negative_part() -> None:
    with pytest.raises(SilverPathError):
        silver_key("firms", "hotspot", "2026-11-14", part=-1)


@pytest.mark.parametrize("run_id", ["../run", "run/1", ""])
def test_rejects_unsafe_run_id(run_id: str) -> None:
    with pytest.raises(SilverPathError):
        manifest_key(run_id)
