"""Open-Meteo raw ingestion into Garage Bronze."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from common.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES, Settings
from common.storage import BronzeStorageError, BronzeStore, ObjectNotFoundError, sha256_hex
from ingest.openmeteo.client import FetchResult, OpenMeteoClient
from ingest.openmeteo.locations import City

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetError:
    dataset: str
    error_type: str
    message: str


@dataclass(frozen=True)
class CityIngestResult:
    city: City
    entries: list[dict[str, Any]]
    errors: list[DatasetError]


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def run_date_from_run_id(run_id: str) -> str:
    date_part = run_id[:8]
    try:
        parsed = datetime.strptime(date_part, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Invalid run_id {run_id!r}; expected YYYYMMDDTHHMMSSZ-suffix") from exc
    return parsed.strftime("%Y-%m-%d")


def object_key(prefix: str, dataset: str, run_id: str, city: City) -> str:
    ingest_date = run_date_from_run_id(run_id)
    return (
        f"{prefix.strip('/')}/{dataset}"
        f"/ingest_date={ingest_date}/run_id={run_id}/{city.slug}.json"
    )


def manifest_key(prefix: str, run_id: str) -> str:
    ingest_date = run_date_from_run_id(run_id)
    return f"{prefix.strip('/')}/manifests/ingest_date={ingest_date}/run_id={run_id}.json"


def build_envelope(
    *,
    result: FetchResult,
    city: City,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "open-meteo",
        "dataset": result.dataset,
        "city": city.as_dict(),
        "endpoint": result.endpoint,
        "ingestion_timestamp": utc_now_iso(),
        "run_id": run_id,
        "request_parameters": result.request_parameters,
        "record_count": result.record_count,
        "response": result.response,
    }


def _datasets(client: OpenMeteoClient) -> tuple[tuple[str, Any], ...]:
    return (
        ("weather", client.fetch_weather),
        ("air_quality", client.fetch_air_quality),
    )


def ingest_city(
    *,
    city: City,
    client: OpenMeteoClient,
    store: BronzeStore,
    run_id: str,
    prefix: str,
) -> CityIngestResult:
    entries: list[dict[str, Any]] = []
    errors: list[DatasetError] = []

    for dataset, fetcher in _datasets(client):
        try:
            result: FetchResult = fetcher(city.latitude, city.longitude)
            payload = build_envelope(result=result, city=city, run_id=run_id)
            key = object_key(prefix, dataset, run_id, city)
            digest = store.put_json(
                key,
                payload,
                metadata={
                    "run-id": run_id,
                    "source": "open-meteo",
                    "dataset": dataset,
                    "city-slug": city.slug,
                },
            )
            head = store.head_object(key)
            readback_digest = store.readback_sha256(key)
            if readback_digest != digest:
                raise BronzeStorageError(
                    f"Readback checksum mismatch for s3://{store.bucket}/{key}"
                )

            readback = store.read_json(key)
            if readback.get("run_id") != run_id:
                raise BronzeStorageError(f"Readback run_id mismatch for {key}")
            if readback.get("record_count") != result.record_count:
                raise BronzeStorageError(f"Readback record_count mismatch for {key}")
            if readback.get("response") != result.response:
                raise BronzeStorageError(f"Readback raw response mismatch for {key}")

            entries.append(
                {
                    "dataset": dataset,
                    "city": city.name,
                    "province": city.province,
                    "latitude": city.latitude,
                    "longitude": city.longitude,
                    "key": key,
                    "record_count": result.record_count,
                    "sha256": digest,
                    "size_bytes": int(head.get("ContentLength", 0)),
                    "endpoint": result.endpoint,
                }
            )
            logger.info(
                "Stored %s/%s records=%d key=%s",
                city.name,
                dataset,
                result.record_count,
                key,
            )
        except Exception as exc:  # noqa: BLE001 - per-dataset isolation is intentional
            errors.append(
                DatasetError(
                    dataset=dataset,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            logger.exception("Failed to ingest %s/%s", city.name, dataset)

    return CityIngestResult(city=city, entries=entries, errors=errors)


def config_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "garage": {
            "endpoint": settings.garage.endpoint,
            "region": settings.garage.region,
            "bucket": settings.garage.bucket,
            "prefix": settings.garage.prefix,
            "force_path_style": settings.garage.force_path_style,
        },
        "openmeteo": {
            "weather_url": settings.openmeteo.weather_url,
            "air_quality_url": settings.openmeteo.air_quality_url,
            "timezone": settings.openmeteo.timezone,
            "forecast_days": settings.openmeteo.forecast_days,
            "past_days": settings.openmeteo.past_days,
            "weather_variables": list(WEATHER_VARIABLES),
            "air_quality_variables": list(AIR_QUALITY_VARIABLES),
        },
    }


def build_manifest(
    *,
    cities: Sequence[City],
    entries: Sequence[dict[str, Any]],
    failures: Sequence[dict[str, Any]],
    settings: Settings,
    run_id: str,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    if failures and entries:
        status = "partial"
    elif failures:
        status = "failed"
    else:
        status = "success"

    requested_cities = {
        (city.name.casefold(), city.province.casefold()) for city in cities
    }
    failed_cities = {
        (failure["city"].casefold(), failure["province"].casefold()) for failure in failures
    }
    successful_cities = requested_cities - failed_cities

    return {
        "schema_version": 1,
        "source": "open-meteo",
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "ingestion_timestamp": finished_at,
        "config": config_snapshot(settings),
        "summary": {
            "cities_requested": len(cities),
            "cities_succeeded": len(successful_cities),
            "cities_failed": len(failed_cities),
            "objects_written": len(entries),
            "records_written": sum(int(entry["record_count"]) for entry in entries),
        },
        "entries": list(entries),
        "failures": list(failures),
    }


def ingest_cities(
    cities: Sequence[City],
    *,
    client: OpenMeteoClient,
    store: BronzeStore,
    run_id: str,
    settings: Settings,
) -> tuple[dict[str, Any], str]:
    started_at = utc_now_iso()
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, city in enumerate(cities, start=1):
        logger.info("[%d/%d] Ingesting %s (%s)", index, len(cities), city.name, city.province)
        result = ingest_city(
            city=city,
            client=client,
            store=store,
            run_id=run_id,
            prefix=settings.garage.prefix,
        )
        entries.extend(result.entries)
        for error in result.errors:
            failures.append(
                {
                    "dataset": error.dataset,
                    "city": city.name,
                    "province": city.province,
                    "error_type": error.error_type,
                    "message": error.message,
                }
            )

    finished_at = utc_now_iso()
    manifest = build_manifest(
        cities=cities,
        entries=entries,
        failures=failures,
        settings=settings,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
    )
    key = manifest_key(settings.garage.prefix, run_id)
    store.put_json(
        key,
        manifest,
        metadata={"run-id": run_id, "source": "open-meteo", "kind": "manifest"},
    )
    logger.info(
        "Manifest written: s3://%s/%s (status=%s)",
        store.bucket,
        key,
        manifest["status"],
    )
    return manifest, key


def _find_manifest_key(store: BronzeStore, run_id: str, prefix: str) -> str:
    candidate = manifest_key(prefix, run_id)
    if store.object_exists(candidate):
        return candidate

    suffix = f"/run_id={run_id}.json"
    manifest_prefix = f"{prefix.strip('/')}/manifests/"
    matches = [key for key in store.list_keys(manifest_prefix) if key.endswith(suffix)]
    if not matches:
        raise ObjectNotFoundError(f"Manifest for run_id {run_id!r} not found")
    if len(matches) > 1:
        raise BronzeStorageError(f"Multiple manifests found for run_id {run_id!r}")
    return matches[0]


def verify_run(
    store: BronzeStore,
    run_id: str,
    *,
    prefix: str,
) -> dict[str, Any]:
    key = _find_manifest_key(store, run_id, prefix)
    manifest = store.read_json(key)
    entries = manifest.get("entries", [])
    verified: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for entry in entries:
        object_key_value = entry.get("key", "")
        try:
            head = store.head_object(object_key_value)
            body = store.read_bytes(object_key_value)
            digest = sha256_hex(body)
            if digest != entry.get("sha256"):
                raise BronzeStorageError(
                    f"Checksum mismatch for {object_key_value}: "
                    f"expected {entry.get('sha256')}, got {digest}"
                )

            payload = json.loads(body.decode("utf-8"))
            if payload.get("run_id") != run_id:
                raise BronzeStorageError(f"run_id mismatch inside {object_key_value}")
            if payload.get("record_count") != entry.get("record_count"):
                raise BronzeStorageError(f"record_count mismatch inside {object_key_value}")

            verified.append(
                {
                    "key": object_key_value,
                    "dataset": entry.get("dataset"),
                    "city": entry.get("city"),
                    "record_count": payload.get("record_count"),
                    "sha256": digest,
                    "size_bytes": int(head.get("ContentLength", len(body))),
                }
            )
        except Exception as exc:  # noqa: BLE001 - collect all readback failures
            failures.append(
                {
                    "key": object_key_value,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    return {
        "run_id": run_id,
        "manifest_key": key,
        "manifest_status": manifest.get("status"),
        "objects_expected": len(entries),
        "objects_verified": len(verified),
        "records_verified": sum(int(item["record_count"] or 0) for item in verified),
        "ok": not failures and bool(entries),
        "verified": verified,
        "failures": failures,
    }
