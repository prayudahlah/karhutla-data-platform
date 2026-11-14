from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from common.config import FirmsBackfillSettings
from ingest.firms_backfill.client import (
    FirmsAreaClient,
    FirmsBackfillError,
    MissingMapKeyError,
    month_windows,
)
from ingest.firms_backfill.ingest import backfill_month, object_key, serialize_jsonl

CSV_HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
)
CSV_ROW = "-8.5,140.9,330.1,0.5,0.4,2026-09-08,0325,N20,VIIRS,nominal,2.0NRT,290.1,4.2,D\n"


class FakeStore:
    bucket = "lakehouse"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_bytes(self, key: str, body: bytes, **_: Any) -> str:
        if key in self.objects and not _.get("overwrite"):
            from common.storage import ObjectAlreadyExistsError

            raise ObjectAlreadyExistsError(key)
        self.objects[key] = body
        return "sha"

    def put_json(self, key: str, payload: Any, **_: Any) -> str:
        self.objects[key] = json.dumps(payload).encode()
        return "sha"


class FakeClient:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, date, int]] = []

    def fetch_window(self, source: str, start: date, days: int) -> list[dict[str, str]]:
        self.calls.append((source, start, days))
        return self.rows

    def close(self) -> None:
        pass


def _settings(**overrides: Any) -> FirmsBackfillSettings:
    base = {
        "map_key": "kunci",
        "sources": ("VIIRS_NOAA20_NRT",),
        "window_days": 5,
    }
    base.update(overrides)
    return FirmsBackfillSettings(**base)


def test_month_windows_split_september() -> None:
    windows = month_windows("2026-09")

    assert len(windows) == 6
    assert windows[0] == (date(2026, 9, 1), date(2026, 9, 5))
    assert windows[-1] == (date(2026, 9, 26), date(2026, 9, 30))


def test_month_windows_cover_leap_february() -> None:
    windows = month_windows("2024-02")

    assert windows[-1][1] == date(2024, 2, 29)
    assert sum((end - start).days + 1 for start, end in windows) == 29


def test_client_parses_csv() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/area/csv/kunci/VIIRS_NOAA20_NRT/" in str(request.url)
        return httpx.Response(200, text=CSV_HEADER + CSV_ROW)

    with FirmsAreaClient(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as client:
        rows = client.fetch_window("VIIRS_NOAA20_NRT", date(2026, 9, 1), 5)

    assert len(rows) == 1
    assert rows[0]["satellite"] == "N20"


def test_client_rejects_non_csv() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Invalid MAP_KEY")

    with FirmsAreaClient(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as client:
        with pytest.raises(FirmsBackfillError):
            client.fetch_window("VIIRS_NOAA20_NRT", date(2026, 9, 1), 5)


def test_client_requires_map_key() -> None:
    client = FirmsAreaClient(_settings(map_key=""))

    with pytest.raises(MissingMapKeyError):
        client.fetch_window("VIIRS_NOAA20_NRT", date(2026, 9, 1), 5)


def test_object_key_is_stable() -> None:
    key = object_key(
        "bronze/firms",
        source="VIIRS_NOAA20_NRT",
        period="2026-09",
        start="2026-09-01",
        end="2026-09-05",
    )

    assert key == (
        "bronze/firms/dataset=hotspot/source=VIIRS_NOAA20_NRT"
        "/period=2026-09"
        "/part-backfill-VIIRS_NOAA20_NRT-2026-09-01-2026-09-05.jsonl"
    )


def test_serialize_jsonl_ends_with_newline() -> None:
    body = serialize_jsonl([{"a": 1}, {"a": 2}])

    assert body.endswith(b"\n")
    assert len(body.splitlines()) == 2


def test_backfill_writes_jsonl_and_manifest() -> None:
    store = FakeStore()
    client = FakeClient(
        [
            json.loads(
                json.dumps(
                    {
                        "latitude": "-8.5",
                        "longitude": "140.9",
                        "acq_date": "2026-09-08",
                        "acq_time": "0325",
                        "satellite": "N20",
                    }
                )
            )
        ]
    )

    result = backfill_month(
        store,
        _settings(),
        month="2026-09",
        prefix="bronze/firms",
        run_id="run-1",
        client=client,
    )

    assert result["windows"] == 6
    assert result["events_written"] == 6
    assert result["status"] == "success"
    assert len(client.calls) == 6
    assert result["manifest_key"] in store.objects


def test_backfill_is_idempotent_without_overwrite() -> None:
    store = FakeStore()
    client = FakeClient(
        [
            {
                "latitude": "-8.5",
                "longitude": "140.9",
                "acq_date": "2026-09-08",
                "acq_time": "0325",
                "satellite": "N20",
            }
        ]
    )
    backfill_month(
        store, _settings(), month="2026-09", prefix="bronze/firms", run_id="run-1", client=client
    )

    second = backfill_month(
        store,
        _settings(),
        month="2026-09",
        prefix="bronze/firms",
        run_id="run-2",
        client=client,
    )

    assert second["windows_skipped"] == 6
    assert second["events_written"] == 0
