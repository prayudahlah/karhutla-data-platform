from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from batch.silver.openmeteo import parse_bronze_object
from common.config import (
    AIR_QUALITY_VARIABLES,
    WEATHER_VARIABLES,
    OpenMeteoSettings,
)
from ingest.openmeteo.backfill import (
    ArchiveClient,
    OpenMeteoBackfillError,
    backfill_months,
    month_bounds,
    object_key,
)
from ingest.openmeteo.locations import City


class FakeStore:
    bucket = "lakehouse"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_json(self, key: str, payload: Any, **_: Any) -> str:
        if key in self.objects and not _.get("overwrite"):
            from common.storage import ObjectAlreadyExistsError

            raise ObjectAlreadyExistsError(key)
        self.objects[key] = json.dumps(payload).encode()
        return "sha"


class FakeArchive:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def fetch_month(self, dataset: str, city: City, month: str):
        self.calls.append((dataset, city.name, month))
        variables = WEATHER_VARIABLES if dataset == "weather" else AIR_QUALITY_VARIABLES
        hourly = {"time": ["2026-09-01T00:00", "2026-09-01T01:00"]}
        hourly.update({name: [1.0, 2.0] for name in variables})
        payload = {"hourly": hourly, "timezone": "Asia/Jakarta"}
        return payload, {"latitude": city.latitude}, 2

    def close(self) -> None:
        pass


def _city(number: int = 1) -> City:
    return City(
        name="Kota Banda Aceh",
        province="Aceh",
        latitude=5.55,
        longitude=95.3175,
        number=number,
    )


def test_month_bounds_for_september() -> None:
    assert month_bounds("2026-09") == (date(2026, 9, 1), date(2026, 9, 30))


def test_month_bounds_for_leap_february() -> None:
    assert month_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def test_object_key_uses_period_partition() -> None:
    key = object_key("bronze/open_meteo", dataset="weather", period="2026-09", slug="01_aceh")

    assert key == ("bronze/open_meteo/dataset=weather/period=2026-09/run_id=backfill/01_aceh.json")


def test_archive_client_builds_request_and_counts_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "start_date=2026-09-01" in str(request.url)
        assert "end_date=2026-09-30" in str(request.url)
        hourly = {"time": ["2026-09-01T00:00"], **{v: [1.0] for v in WEATHER_VARIABLES}}
        return httpx.Response(200, json={"hourly": hourly})

    settings = OpenMeteoSettings()
    with ArchiveClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as c:
        payload, params, count = c.fetch_month("weather", _city(), "2026-09")

    assert count == 1
    assert params["start_date"] == "2026-09-01"
    assert payload["hourly"]["time"] == ["2026-09-01T00:00"]


def test_archive_client_rejects_missing_variable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hourly": {"time": ["x"]}})

    settings = OpenMeteoSettings()
    with ArchiveClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as c:
        with pytest.raises(OpenMeteoBackfillError):
            c.fetch_month("weather", _city(), "2026-09")


def test_backfill_writes_envelopes_with_period() -> None:
    store = FakeStore()
    archive = FakeArchive()

    result = backfill_months(
        store,
        OpenMeteoSettings(),
        months=["2026-09"],
        locations=[_city()],
        prefix="bronze/open_meteo",
        run_id="run-1",
        client=archive,
    )

    assert result["objects_written"] == 2
    assert result["records_written"] == 4
    assert len(archive.calls) == 2
    keys = sorted(store.objects)
    assert any("dataset=weather/period=2026-09" in k for k in keys)
    assert any("dataset=air_quality/period=2026-09" in k for k in keys)
    envelope = json.loads(store.objects[[k for k in keys if "weather" in k][0]])
    assert envelope["backfill"] is True
    assert envelope["city"]["province"] == "Aceh"


def test_backfill_is_idempotent() -> None:
    store = FakeStore()
    archive = FakeArchive()
    backfill_months(
        store,
        OpenMeteoSettings(),
        months=["2026-09"],
        locations=[_city()],
        prefix="bronze/open_meteo",
        run_id="run-1",
        client=archive,
    )

    second = backfill_months(
        store,
        OpenMeteoSettings(),
        months=["2026-09"],
        locations=[_city()],
        prefix="bronze/open_meteo",
        run_id="run-2",
        client=archive,
    )

    assert second["objects_skipped"] == 2
    assert second["objects_written"] == 0


def test_silver_parser_accepts_period_partition() -> None:
    key = "bronze/open_meteo/dataset=weather/period=2026-09/run_id=backfill/01_aceh.json"

    parsed = parse_bronze_object(key, prefix="bronze/open_meteo", dataset="weather")

    assert parsed is not None
    assert parsed.ingest_date == date(2026, 9, 1)
    assert parsed.run_id == "backfill"


def test_silver_parser_still_accepts_ingest_date() -> None:
    key = "bronze/open_meteo/dataset=weather/ingest_date=2026-11-14/run_id=run-1/01_aceh.json"

    parsed = parse_bronze_object(key, prefix="bronze/open_meteo", dataset="weather")

    assert parsed is not None
    assert parsed.ingest_date == date(2026, 11, 14)
