"""Thin Open-Meteo client for weather and air-quality raw responses."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from common.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES, OpenMeteoSettings

logger = logging.getLogger(__name__)


class OpenMeteoError(RuntimeError):
    """Base error for Open-Meteo ingestion."""


class OpenMeteoAPIError(OpenMeteoError):
    """Raised when Open-Meteo returns a non-retryable or exhausted response."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OpenMeteoValidationError(OpenMeteoError):
    """Raised when an Open-Meteo response is missing required raw fields."""


@dataclass(frozen=True)
class FetchResult:
    dataset: str
    endpoint: str
    request_parameters: dict[str, Any]
    response: dict[str, Any]
    record_count: int


class OpenMeteoClient:
    def __init__(
        self,
        settings: OpenMeteoSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "karhutla-data-platform/0.1 (+batch-bronze)"},
        )

    def __enter__(self) -> OpenMeteoClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _build_params(
        self,
        latitude: float,
        longitude: float,
        variables: tuple[str, ...],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(variables),
            "timezone": self.settings.timezone,
            "forecast_days": self.settings.forecast_days,
        }
        if self.settings.past_days > 0:
            params["past_days"] = self.settings.past_days
        return params

    def _sleep_before_retry(self, attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = min(2**attempt, 30)
        else:
            delay = min(2**attempt, 30)
        delay += random.uniform(0, 0.5)
        logger.warning("Open-Meteo retry %d in %.1fs", attempt + 1, delay)
        time.sleep(delay)

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        attempts = max(1, self.settings.max_retries)
        last_error: str = "unknown error"

        for attempt in range(attempts):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                if attempt + 1 >= attempts:
                    raise OpenMeteoAPIError(
                        f"Open-Meteo request failed after {attempts} attempts: {exc}"
                    ) from exc
                self._sleep_before_retry(attempt, None)
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise OpenMeteoValidationError(
                        f"Open-Meteo returned non-JSON response from {url}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise OpenMeteoValidationError(
                        f"Open-Meteo returned unexpected JSON type: {type(payload).__name__}"
                    )
                return payload

            body = response.text[:500]
            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            last_error = f"HTTP {response.status_code}: {body}"
            if retryable and attempt + 1 < attempts:
                self._sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue

            raise OpenMeteoAPIError(
                f"Open-Meteo request failed with HTTP {response.status_code}: {body}",
                status_code=response.status_code,
                body=body,
            )

        raise OpenMeteoAPIError(f"Open-Meteo request failed: {last_error}")

    @staticmethod
    def _validate_hourly(payload: dict[str, Any], variables: tuple[str, ...]) -> int:
        if "error" in payload:
            raise OpenMeteoValidationError(f"Open-Meteo error payload: {payload['error']}")

        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            raise OpenMeteoValidationError("Open-Meteo response has no 'hourly' object")

        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise OpenMeteoValidationError("Open-Meteo response has empty 'hourly.time'")

        missing = [name for name in variables if name not in hourly]
        if missing:
            raise OpenMeteoValidationError(
                "Open-Meteo response is missing hourly variables: " + ", ".join(missing)
            )

        wrong_length = [
            name
            for name in variables
            if not isinstance(hourly[name], list) or len(hourly[name]) != len(times)
        ]
        if wrong_length:
            raise OpenMeteoValidationError(
                "Open-Meteo hourly variables have inconsistent lengths: "
                + ", ".join(wrong_length)
            )

        return len(times)

    def fetch_weather(self, latitude: float, longitude: float) -> FetchResult:
        params = self._build_params(latitude, longitude, WEATHER_VARIABLES)
        payload = self._get(self.settings.weather_url, params)
        record_count = self._validate_hourly(payload, WEATHER_VARIABLES)
        return FetchResult(
            dataset="weather",
            endpoint=self.settings.weather_url,
            request_parameters=params,
            response=payload,
            record_count=record_count,
        )

    def fetch_air_quality(self, latitude: float, longitude: float) -> FetchResult:
        params = self._build_params(latitude, longitude, AIR_QUALITY_VARIABLES)
        payload = self._get(self.settings.air_quality_url, params)
        record_count = self._validate_hourly(payload, AIR_QUALITY_VARIABLES)
        return FetchResult(
            dataset="air_quality",
            endpoint=self.settings.air_quality_url,
            request_parameters=params,
            response=payload,
            record_count=record_count,
        )
