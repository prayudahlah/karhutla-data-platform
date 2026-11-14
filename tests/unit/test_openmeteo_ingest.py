from __future__ import annotations

import json
from typing import Any

import pytest

from common.config import GarageSettings, OpenMeteoSettings, Settings
from common.storage import (
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    serialize_json,
    sha256_hex,
)
from ingest.openmeteo.client import FetchResult, OpenMeteoAPIError
from ingest.openmeteo.ingest import (
    ingest_cities,
    object_key,
    run_date_from_run_id,
    verify_run,
)
from ingest.openmeteo.locations import City


class FakeStore:
    bucket = "lakehouse"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_json(
        self,
        key: str,
        payload: Any,
        *,
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        if key in self.objects and not overwrite:
            raise ObjectAlreadyExistsError(key)
        body = serialize_json(payload)
        self.objects[key] = body
        return sha256_hex(body)

    def head_object(self, key: str) -> dict[str, Any]:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return {"ContentLength": len(self.objects[key])}

    def read_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]

    def readback_sha256(self, key: str) -> str:
        return sha256_hex(self.objects[key])

    def read_json(self, key: str) -> Any:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return json.loads(self.objects[key].decode("utf-8"))

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


class FakeOpenMeteoClient:
    def __init__(self, *, fail_air_quality: bool = False) -> None:
        self.fail_air_quality = fail_air_quality

    @staticmethod
    def _result(dataset: str, endpoint: str) -> FetchResult:
        return FetchResult(
            dataset=dataset,
            endpoint=endpoint,
            request_parameters={"latitude": 0.5, "hourly": ["temperature_2m"]},
            response={
                "latitude": 0.5,
                "longitude": 101.4,
                "hourly": {"time": ["2026-11-14T00:00"], "value": [1.0]},
            },
            record_count=1,
        )

    def fetch_weather(self, latitude: float, longitude: float) -> FetchResult:
        return self._result("weather", "https://weather.test/forecast")

    def fetch_air_quality(self, latitude: float, longitude: float) -> FetchResult:
        if self.fail_air_quality:
            raise OpenMeteoAPIError("air quality unavailable", status_code=503)
        return self._result("air_quality", "https://air.test/air-quality")


def _settings() -> Settings:
    return Settings(
        garage=GarageSettings(
            endpoint="http://127.0.0.1:3900",
            region="garage",
            access_key_id="test",
            secret_access_key="test",
            bucket="lakehouse",
            prefix="bronze/open_meteo",
        ),
        openmeteo=OpenMeteoSettings(forecast_days=1),
    )


def _city() -> City:
    return City(name="Kota Pekanbaru", province="Riau", latitude=0.5333, longitude=101.45)


RUN_ID = "20261114T010203Z-deadbeef"


def test_object_key_prefixes_sequence_number() -> None:
    numbered = City(
        name="Banda Aceh",
        province="Aceh",
        latitude=5.5483,
        longitude=95.3238,
        number=1,
    )

    key = object_key("bronze/open_meteo", "weather", RUN_ID, numbered)

    assert key == (
        "bronze/open_meteo/dataset=weather/ingest_date=2026-11-14/"
        f"run_id={RUN_ID}/01_banda_aceh_aceh.json"
    )


def test_ingest_cities_writes_both_datasets_and_manifest() -> None:
    store = FakeStore()
    settings = _settings()

    manifest, key = ingest_cities(
        [_city()],
        client=FakeOpenMeteoClient(),
        store=store,  # type: ignore[arg-type]
        run_id=RUN_ID,
        settings=settings,
    )

    assert manifest["status"] == "success"
    assert manifest["summary"] == {
        "cities_requested": 1,
        "cities_succeeded": 1,
        "cities_failed": 0,
        "objects_written": 2,
        "records_written": 2,
    }
    assert key == (
        "bronze/open_meteo/manifests/ingest_date=2026-11-14/"
        f"run_id={RUN_ID}.json"
    )

    weather_key = object_key("bronze/open_meteo", "weather", RUN_ID, _city())
    air_key = object_key("bronze/open_meteo", "air_quality", RUN_ID, _city())
    assert weather_key in store.objects
    assert air_key in store.objects

    envelope = store.read_json(weather_key)
    assert envelope["source"] == "open-meteo"
    assert envelope["dataset"] == "weather"
    assert envelope["run_id"] == RUN_ID
    assert envelope["record_count"] == 1
    assert envelope["request_parameters"]
    assert envelope["ingestion_timestamp"].endswith("Z")
    assert envelope["city"]["name"] == "Kota Pekanbaru"


def test_verify_run_reads_back_all_objects() -> None:
    store = FakeStore()
    settings = _settings()
    ingest_cities(
        [_city()],
        client=FakeOpenMeteoClient(),
        store=store,  # type: ignore[arg-type]
        run_id=RUN_ID,
        settings=settings,
    )

    result = verify_run(
        store,  # type: ignore[arg-type]
        RUN_ID,
        prefix=settings.garage.prefix,
    )

    assert result["ok"] is True
    assert result["objects_expected"] == 2
    assert result["objects_verified"] == 2
    assert result["records_verified"] == 2


def test_partial_failure_is_recorded_in_manifest() -> None:
    store = FakeStore()
    settings = _settings()

    manifest, _ = ingest_cities(
        [_city()],
        client=FakeOpenMeteoClient(fail_air_quality=True),
        store=store,  # type: ignore[arg-type]
        run_id=RUN_ID,
        settings=settings,
    )

    assert manifest["status"] == "partial"
    assert manifest["summary"]["objects_written"] == 1
    assert manifest["summary"]["cities_failed"] == 1
    assert len(manifest["failures"]) == 1
    assert manifest["failures"][0]["dataset"] == "air_quality"
    assert manifest["failures"][0]["error_type"] == "OpenMeteoAPIError"


def test_all_failures_produce_failed_manifest() -> None:
    class BrokenClient(FakeOpenMeteoClient):
        def fetch_weather(self, latitude: float, longitude: float) -> FetchResult:
            raise OpenMeteoAPIError("weather unavailable", status_code=500)

        def fetch_air_quality(self, latitude: float, longitude: float) -> FetchResult:
            raise OpenMeteoAPIError("air unavailable", status_code=500)

    store = FakeStore()
    manifest, _ = ingest_cities(
        [_city()],
        client=BrokenClient(),
        store=store,  # type: ignore[arg-type]
        run_id=RUN_ID,
        settings=_settings(),
    )

    assert manifest["status"] == "failed"
    assert manifest["summary"]["objects_written"] == 0
    assert len(manifest["failures"]) == 2


def test_run_date_from_run_id_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid run_id"):
        run_date_from_run_id("not-a-run-id")
