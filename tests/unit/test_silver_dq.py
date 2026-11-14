from __future__ import annotations

import json
from typing import Any

from batch.silver.dq import (
    DQReport,
    check_not_null,
    check_row_count,
    check_unique,
    quarantine_table,
    write_quarantine,
)
from batch.silver.parquet import read_parquet_bytes


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
        self.objects[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return key

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]["body"]


def test_report_status_and_serialization() -> None:
    report = DQReport(source="open_meteo", dataset="weather", run_id="run-1")
    report.input_rows = 10
    report.accepted_rows = 9
    report.rejected_rows = 1
    report.add_check("row_count", False, actual=9, expected=10)
    report.add_check("nulls", True, null_counts={})

    payload = report.as_dict()
    assert report.status == "failed"
    assert payload["counts"] == {
        "input_rows": 10,
        "accepted_rows": 9,
        "rejected_rows": 1,
        "duplicate_rows": 0,
    }
    assert [check["name"] for check in payload["checks"]] == ["row_count", "nulls"]


def test_empty_report_fails_closed() -> None:
    report = DQReport(source="open_meteo", dataset="weather", run_id="run-1")
    assert report.status == "failed"


def test_report_write_uses_json_metadata() -> None:
    store = FakeStore()
    report = DQReport(source="open_meteo", dataset="weather", run_id="run-1")
    report.add_check("row_count", True, actual=1, expected=1)

    key = report.write(store, "silver/_dq/open_meteo/dataset=weather/run_id=run-1.json")
    stored = store.objects[key]

    assert stored["content_type"] == "application/json"
    assert stored["metadata"]["kind"] == "silver-dq-report"
    assert json.loads(stored["body"])["status"] == "passed"


def test_row_count_check() -> None:
    assert check_row_count("rows", 3, 3).passed
    failed = check_row_count("rows", 2, 3)
    assert not failed.passed
    assert failed.details["difference"] == -1


def test_unique_check_reports_duplicates() -> None:
    passed = check_unique("keys", ["a", "b", "c"])
    assert passed.passed
    assert passed.details["duplicate_rows"] == 0

    failed = check_unique("keys", ["a", "a", "b", "b", "b"])
    assert not failed.passed
    assert failed.details["duplicate_rows"] == 3
    assert failed.details["duplicate_keys"] == 2


def test_not_null_check() -> None:
    rows = [{"a": 1, "b": None}, {"a": 2, "b": "x"}]
    failed = check_not_null("required", rows, ["a", "b"])
    assert not failed.passed
    assert failed.details["null_counts"] == {"a": 0, "b": 1}


def test_quarantine_table_keeps_original_payload() -> None:
    table = quarantine_table(
        [{"id": 1, "value": None}],
        source="open_meteo",
        dataset="weather",
        reason="null_required_field",
        run_id="run-1",
    )

    row = table.to_pylist()[0]
    assert row["source"] == "open_meteo"
    assert row["dataset"] == "weather"
    assert row["reason"] == "null_required_field"
    assert json.loads(row["payload"]) == {"id": 1, "value": None}


def test_quarantine_table_supports_empty_input() -> None:
    table = quarantine_table(
        [],
        source="open_meteo",
        dataset="weather",
        reason="none",
        run_id="run-1",
    )
    assert table.num_rows == 0
    assert table.column_names == [
        "source",
        "dataset",
        "run_id",
        "reason",
        "payload",
        "quarantined_at",
    ]


def test_write_quarantine_uploads_parquet() -> None:
    store = FakeStore()
    key = write_quarantine(
        store,
        "silver/_quarantine/open_meteo/dataset=weather/date=2026-11-14/part-00000.parquet",
        [{"id": 1}],
        source="open_meteo",
        dataset="weather",
        reason="bad_row",
        run_id="run-1",
    )

    stored = store.objects[key]
    assert stored["content_type"] == "application/vnd.apache.parquet"
    assert stored["metadata"]["kind"] == "silver-quarantine"
    assert read_parquet_bytes(stored["body"]).num_rows == 1
