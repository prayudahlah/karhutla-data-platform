from __future__ import annotations

import io
import json
from datetime import date, datetime
from typing import Any

import pyarrow.parquet as pq
import pytest

from batch.silver.firms import (
    FirmsEventError,
    FirmsSilverError,
    ingest_date_from_key,
    normalize,
    parse_event,
    parse_jsonl,
)
from common.config import (
    BurnedAreaSettings,
    FirmsBronzeSettings,
    GarageSettings,
    OpenMeteoSettings,
    Settings,
)

BBOX = (95.0, -11.0, 141.0, 6.0)
KEY = (
    "bronze/firms/dataset=hotspot/source=VIIRS_NOAA20_NRT"
    "/ingest_date=2026-11-14/ingest_hour=07"
    "/part-p0-000000000001-000000000002.jsonl"
)


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        if key in self.objects and not overwrite:
            raise FileExistsError(key)
        self.objects[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return "sha"

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]["body"]

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


def _settings() -> Settings:
    return Settings(
        garage=GarageSettings(
            endpoint="http://127.0.0.1:3900",
            region="garage",
            access_key_id="key",
            secret_access_key="secret",
            bucket="lakehouse",
        ),
        openmeteo=OpenMeteoSettings(),
        firms_bronze=FirmsBronzeSettings(prefix="bronze/firms"),
        burned_area=BurnedAreaSettings(bbox=BBOX),
    )


def _event(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "event_id": "e1",
        "schema_version": 1,
        "source": "VIIRS_NOAA20_NRT",
        "satellite": "N20",
        "instrument": "VIIRS",
        "latitude": -0.5,
        "longitude": 101.5,
        "acq_date": "2026-09-08",
        "acq_time": 712,
        "acq_ts_utc": "2026-09-08T07:12:00Z",
        "ingested_at": "2026-09-08T09:00:00Z",
        "confidence": "nominal",
        "frp": 4.2,
        "bright_ti4": 330.1,
        "bright_ti5": 290.3,
        "scan": 0.5,
        "track": 0.4,
        "daynight": "D",
        "version": "2.0NRT",
    }
    base.update(overrides)
    return json.dumps(base)


def test_parse_event_keeps_core_fields_and_zero_pads_time() -> None:
    row = parse_event(_event(), source_file=KEY, bbox=BBOX)

    assert row["acq_time"] == "0712"
    assert row["acq_date"] == date(2026, 9, 8)
    assert row["acq_ts_utc"] == datetime(2026, 9, 8, 7, 12)
    assert row["brightness"] == pytest.approx(330.1)
    assert row["brightness_secondary"] == pytest.approx(290.3)
    assert row["in_bbox"] is True


def test_parse_event_converts_to_jakarta_time() -> None:
    row = parse_event(_event(), source_file=KEY, bbox=BBOX)

    assert row["acq_ts_local"] == datetime(2026, 9, 8, 14, 12)


def test_parse_event_reads_modis_numeric_confidence() -> None:
    row = parse_event(
        _event(source="MODIS_NRT", confidence=85, bright_ti4=None, brightness=312.5),
        source_file=KEY,
        bbox=BBOX,
    )

    assert row["confidence"] == "85"
    assert row["confidence_score"] == 85
    assert row["brightness"] == pytest.approx(312.5)


def test_parse_event_marks_outside_bbox() -> None:
    row = parse_event(_event(latitude=12.0, longitude=101.0), source_file=KEY, bbox=BBOX)

    assert row["in_bbox"] is False


def test_parse_event_rejects_invalid_json() -> None:
    with pytest.raises(FirmsEventError) as exc:
        parse_event("{bukan json", source_file=KEY, bbox=BBOX)

    assert exc.value.reason == "invalid_json"


def test_parse_event_rejects_missing_field() -> None:
    payload = json.loads(_event())
    payload.pop("acq_ts_utc")

    with pytest.raises(FirmsEventError) as exc:
        parse_event(json.dumps(payload), source_file=KEY, bbox=BBOX)

    assert exc.value.reason == "missing_fields"


def test_parse_event_rejects_bad_coordinate() -> None:
    with pytest.raises(FirmsEventError) as exc:
        parse_event(_event(latitude="utara"), source_file=KEY, bbox=BBOX)

    assert exc.value.reason == "bad_coordinate"


def test_parse_event_rejects_bad_timestamp() -> None:
    with pytest.raises(FirmsEventError) as exc:
        parse_event(_event(acq_ts_utc="kemarin"), source_file=KEY, bbox=BBOX)

    assert exc.value.reason == "bad_timestamp"


def test_parse_jsonl_separates_valid_and_rejected() -> None:
    payload = "\n".join([_event(), _event(event_id="e2"), "{rusak"]).encode()

    rows, rejected = parse_jsonl(payload, source_file=KEY, bbox=BBOX)

    assert len(rows) == 2
    assert len(rejected) == 1
    assert rejected[0]["line"] == 3
    assert rejected[0]["reason"] == "invalid_json"


def test_ingest_date_from_key_reads_partition() -> None:
    assert ingest_date_from_key(KEY) == date(2026, 11, 14)


def test_ingest_date_from_key_returns_none_without_partition() -> None:
    assert ingest_date_from_key("bronze/firms/dataset=hotspot/x.jsonl") is None


def _store_with(lines: list[str], key: str = KEY) -> FakeStore:
    store = FakeStore()
    store.objects[key] = {
        "body": "\n".join(lines).encode(),
        "content_type": "application/x-ndjson",
        "metadata": {},
    }
    return store


def test_normalize_writes_parquet_per_acq_date() -> None:
    store = _store_with([_event(event_id="e1"), _event(event_id="e2")])

    summary = normalize(store, _settings(), run_id="20261114T090000Z-abcdef12")

    assert summary["rows_written"] == 2
    assert summary["dq_status"] == "passed"
    parquet_keys = [key for key in store.objects if key.startswith("silver/_normalized/firms/")]
    assert parquet_keys == [
        "silver/_normalized/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"
    ]


def test_normalize_parquet_has_expected_columns() -> None:
    store = _store_with([_event()])

    normalize(store, _settings(), run_id="run-1")

    key = next(k for k in store.objects if k.startswith("silver/_normalized/firms/"))
    table = pq.read_table(io.BytesIO(store.objects[key]["body"]))

    assert table.num_rows == 1
    assert "acq_ts_utc" in table.column_names
    assert "in_bbox" in table.column_names


def test_normalize_reports_duplicate_events_without_dropping() -> None:
    store = _store_with([_event(event_id="sama"), _event(event_id="sama")])

    summary = normalize(store, _settings(), run_id="run-2")

    assert summary["rows_written"] == 2
    assert summary["duplicate_event_ids"] == 1
    # Rasio duplikat 50 persen, jadi DQ menandai anomali.
    assert summary["dq_status"] == "failed"


def test_normalize_quarantines_invalid_lines() -> None:
    store = _store_with([_event(), "{rusak"])

    summary = normalize(store, _settings(), run_id="run-3")

    assert summary["rows_written"] == 1
    assert summary["rows_quarantined"] == 1
    quarantine = [k for k in store.objects if k.startswith("silver/_quarantine/")]
    assert quarantine == [
        "silver/_quarantine/firms/dataset=hotspot/date=2026-11-14/part-00000.parquet"
    ]


def test_normalize_writes_dq_report() -> None:
    store = _store_with([_event()])

    summary = normalize(store, _settings(), run_id="run-4")

    assert summary["dq_report_key"] == "silver/_dq/firms/dataset=hotspot/run_id=run-4.json"
    assert summary["dq_report_key"] in store.objects


def test_normalize_without_bronze_raises() -> None:
    with pytest.raises(FirmsSilverError):
        normalize(FakeStore(), _settings(), run_id="run-5")


def test_main_wires_normalize(monkeypatch) -> None:
    from batch.silver import firms

    captured: dict[str, Any] = {}

    def fake_normalize(store, settings, *, run_id, local_root=None, overwrite=False):
        captured.update(run_id=run_id, local_root=local_root)
        return {"rows_written": 0}

    monkeypatch.setattr(firms, "normalize", fake_normalize)

    class DummySettings:
        garage = object()

        @staticmethod
        def from_env():
            return DummySettings()

    monkeypatch.setattr(firms, "Settings", DummySettings)
    monkeypatch.setattr(firms, "BronzeStore", lambda settings: object())

    assert firms.main(["normalize", "--run-id", "run-x"]) == 0
    assert captured["run_id"] == "run-x"
    assert captured["local_root"] is not None


def test_main_can_disable_local_mirror(monkeypatch) -> None:
    from batch.silver import firms

    captured: dict[str, Any] = {}

    def fake_normalize(store, settings, *, run_id, local_root=None, overwrite=False):
        captured.update(local_root=local_root)
        return {"rows_written": 0}

    monkeypatch.setattr(firms, "normalize", fake_normalize)

    class DummySettings:
        garage = object()

        @staticmethod
        def from_env():
            return DummySettings()

    monkeypatch.setattr(firms, "Settings", DummySettings)
    monkeypatch.setattr(firms, "BronzeStore", lambda settings: object())

    assert firms.main(["normalize", "--run-id", "run-x", "--no-mirror"]) == 0
    assert captured["local_root"] is None
