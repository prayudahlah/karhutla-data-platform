from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from common.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES, OpenMeteoSettings
from ingest.openmeteo.client import (
    OpenMeteoAPIError,
    OpenMeteoClient,
    OpenMeteoValidationError,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _settings(**overrides) -> OpenMeteoSettings:
    values = {
        "weather_url": "https://weather.test/forecast",
        "air_quality_url": "https://air.test/air-quality",
        "timezone": "Asia/Jakarta",
        "forecast_days": 1,
        "past_days": 0,
        "timeout_seconds": 5,
        "max_retries": 3,
    }
    values.update(overrides)
    return OpenMeteoSettings(**values)


def _client(handler, settings: OpenMeteoSettings | None = None) -> OpenMeteoClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=5)
    return OpenMeteoClient(settings or _settings(), client=http_client)


def test_fetch_weather_preserves_raw_response_and_parameters() -> None:
    payload = _fixture("openmeteo_weather.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/forecast"
        assert "temperature_2m" in request.url.params["hourly"]
        assert "et0_fao_evapotranspiration" in request.url.params["hourly"]
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        result = client.fetch_weather(-0.5, 101.4)

    assert result.dataset == "weather"
    assert result.record_count == 3
    assert result.response == payload
    assert result.request_parameters["timezone"] == "Asia/Jakarta"
    assert set(WEATHER_VARIABLES).issubset(result.response["hourly"])


def test_fetch_air_quality_preserves_raw_response() -> None:
    payload = _fixture("openmeteo_air_quality.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/air-quality"
        assert "pm2_5" in request.url.params["hourly"]
        assert "aerosol_optical_depth" in request.url.params["hourly"]
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        result = client.fetch_air_quality(-0.5, 101.4)

    assert result.dataset == "air_quality"
    assert result.record_count == 3
    assert result.response == payload
    assert set(AIR_QUALITY_VARIABLES).issubset(result.response["hourly"])


def test_missing_variable_raises_validation_error() -> None:
    payload = _fixture("openmeteo_air_quality.json")
    del payload["hourly"]["pm2_5"]

    with _client(lambda request: httpx.Response(200, json=payload)) as client:
        with pytest.raises(OpenMeteoValidationError, match="pm2_5"):
            client.fetch_air_quality(-0.5, 101.4)


def test_inconsistent_variable_length_raises_validation_error() -> None:
    payload = _fixture("openmeteo_weather.json")
    payload["hourly"]["temperature_2m"].append(99.0)

    with _client(lambda request: httpx.Response(200, json=payload)) as client:
        with pytest.raises(OpenMeteoValidationError, match="inconsistent"):
            client.fetch_weather(-0.5, 101.4)


def test_non_retryable_http_error_raises_api_error() -> None:
    with _client(lambda request: httpx.Response(400, text="bad request")) as client:
        with pytest.raises(OpenMeteoAPIError) as exc_info:
            client.fetch_weather(-0.5, 101.4)

    assert exc_info.value.status_code == 400


def test_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _fixture("openmeteo_weather.json")
    calls = {"count": 0}
    monkeypatch.setattr("ingest.openmeteo.client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="rate limited")
        return httpx.Response(200, json=payload)

    with _client(handler, _settings(max_retries=3)) as client:
        result = client.fetch_weather(-0.5, 101.4)

    assert calls["count"] == 2
    assert result.record_count == 3


def test_exhausted_retries_raise_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.openmeteo.client.time.sleep", lambda _: None)

    with _client(
        lambda request: httpx.Response(503, text="unavailable"),
        _settings(max_retries=2),
    ) as client:
        with pytest.raises(OpenMeteoAPIError) as exc_info:
            client.fetch_weather(-0.5, 101.4)

    assert exc_info.value.status_code == 503
