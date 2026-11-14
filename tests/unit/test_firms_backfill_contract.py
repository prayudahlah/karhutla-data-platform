from __future__ import annotations

import json

import event_schema
import pytest

from ingest.firms_backfill.contract import (
    acquire_timestamp,
    event_id_from_key,
    make_key,
    to_event,
)

ROW = {
    "latitude": "-8.63542",
    "longitude": "140.91168",
    "acq_date": "2026-09-08",
    "acq_time": "0325",
    "satellite": "N20",
}


def test_key_matches_stream_producer() -> None:
    producer_row = {
        "latitude": -8.63542,
        "longitude": 140.91168,
        "acq_date": "2026-09-08",
        "acq_time": 325,
        "satellite": "N20",
    }

    assert make_key(
        {
            "latitude": -8.63542,
            "longitude": 140.91168,
            "acq_date": "2026-09-08",
            "acq_time": 325,
            "satellite": "N20",
        }
    ) == event_schema.make_key(producer_row)


def test_event_id_matches_stream_producer() -> None:
    key = event_schema.make_key(
        {
            "latitude": -8.63542,
            "longitude": 140.91168,
            "acq_date": "2026-09-08",
            "acq_time": 325,
            "satellite": "N20",
        }
    )

    assert event_id_from_key(key) == event_schema.event_id_from_key(key)


def test_acquire_timestamp_is_utc() -> None:
    assert acquire_timestamp("2026-09-08", "0325") == "2026-09-08T03:25:00Z"


def test_to_event_carries_identity_and_raw_fields() -> None:
    event = to_event(ROW, source="VIIRS_NOAA20_NRT", ingested_at="2026-11-14T10:00:00Z")

    assert event["schema_version"] == 1
    assert event["source"] == "VIIRS_NOAA20_NRT"
    assert event["latitude"] == pytest.approx(-8.63542)
    assert event["acq_time"] == 325
    assert event["acq_ts_utc"] == "2026-09-08T03:25:00Z"
    assert event["ingested_at"] == "2026-11-14T10:00:00Z"
    assert event["event_id"] == event_id_from_key(make_key(ROW))


def test_to_event_keeps_optional_fields_when_present() -> None:
    row = {**ROW, "frp": "4.2", "confidence": "nominal", "daynight": "D", "version": "2.0NRT"}

    event = to_event(row, source="VIIRS_NOAA20_NRT", ingested_at="x")

    assert event["frp"] == "4.2"
    assert event["confidence"] == "nominal"


def test_to_event_skips_empty_optionals() -> None:
    row = {**ROW, "frp": "", "confidence": ""}

    event = to_event(row, source="VIIRS_NOAA20_NRT", ingested_at="x")

    assert "frp" not in event
    assert "confidence" not in event


def test_event_is_json_serializable() -> None:
    event = to_event(ROW, source="VIIRS_NOAA20_NRT", ingested_at="x")

    assert json.loads(json.dumps(event))["acq_date"] == "2026-09-08"
