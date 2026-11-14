"""Backfill cuaca dan kualitas udara Open-Meteo ke Bronze.

Berbeda dengan ingest harian yang memakai endpoint prakiraan, backfill memakai
endpoint arsip dengan rentang tanggal. Satu permintaan mencakup satu bulan untuk
satu lokasi, jadi jauh lebih ringan daripada menarik per hari.

Keluaran memakai partisi ``period=YYYY-MM`` supaya menjalankan ulang bulan yang
sama menghasilkan kunci yang sama. Normalizer Silver menerima kedua bentuk
partisi (``ingest_date=`` dan ``period=``).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import httpx

from common.config import AIR_QUALITY_VARIABLES, WEATHER_VARIABLES, OpenMeteoSettings
from common.run import new_run_id, utc_now_iso
from common.storage import BronzeStore, ObjectAlreadyExistsError
from ingest.openmeteo.locations import City

logger = logging.getLogger(__name__)

DATASETS = ("weather", "air_quality")
VARIABLES = {
    "weather": WEATHER_VARIABLES,
    "air_quality": AIR_QUALITY_VARIABLES,
}


class OpenMeteoBackfillError(RuntimeError):
    """Permintaan arsip gagal atau balasannya tidak lengkap."""


def month_bounds(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end - timedelta(days=1)


BACKFILL_RUN_LABEL = "backfill"


def object_key(prefix: str, *, dataset: str, period: str, slug: str) -> str:
    """Kunci sengaja tidak memuat run id asli.

    Kalau memuat, menjalankan ulang bulan yang sama akan menulis objek baru dan
    backfill tidak pernah idempoten. Segmen run_id tetap ada supaya tata letak
    sejalan dengan ingest harian, isinya label tetap.
    """
    return (
        f"{prefix.strip('/')}/dataset={dataset}"
        f"/period={period}/run_id={BACKFILL_RUN_LABEL}/{slug}.json"
    )


def manifest_key(prefix: str, ingest_date: str, run_id: str) -> str:
    return f"{prefix.strip('/')}/manifests/ingest_date={ingest_date}/run_id={run_id}.json"


class ArchiveClient:
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
            headers={"User-Agent": "karhutla-data-platform/0.1 (+openmeteo-backfill)"},
        )

    def __enter__(self) -> ArchiveClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

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

    def fetch_month(
        self, dataset: str, city: City, month: str
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        """Kembalikan (payload, parameter permintaan, jumlah baris)."""
        url = self.settings.archive_url if dataset == "weather" else self.settings.air_quality_url
        start, end = month_bounds(month)
        params: dict[str, Any] = {
            "latitude": city.latitude,
            "longitude": city.longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(VARIABLES[dataset]),
            "timezone": self.settings.timezone,
        }

        attempts = max(1, self.settings.max_retries)
        for attempt in range(attempts):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt + 1 >= attempts:
                    raise OpenMeteoBackfillError(
                        f"Permintaan gagal setelah {attempts} percobaan "
                        f"({dataset}, {city.name}, {month})"
                    ) from exc
                self._sleep_before_retry(attempt, None)
                continue

            if response.status_code == 200:
                payload = response.json()
                count = self._validate(payload, dataset)
                return payload, params, count

            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < attempts:
                self._sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            raise OpenMeteoBackfillError(
                f"HTTP {response.status_code} untuk {dataset} {city.name} {month}"
            )
        raise OpenMeteoBackfillError(f"Permintaan gagal untuk {dataset} {city.name}")

    @staticmethod
    def _validate(payload: dict[str, Any], dataset: str) -> int:
        if not isinstance(payload, dict):
            raise OpenMeteoBackfillError(f"Balasan {dataset} bukan objek JSON")
        if "error" in payload:
            raise OpenMeteoBackfillError(f"Open-Meteo error: {payload['error']}")
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            raise OpenMeteoBackfillError(f"Balasan {dataset} tanpa 'hourly'")
        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise OpenMeteoBackfillError(f"Balasan {dataset} tanpa deret waktu")
        missing = [name for name in VARIABLES[dataset] if name not in hourly]
        if missing:
            raise OpenMeteoBackfillError("Variabel hilang: " + ", ".join(missing))
        return len(times)


def build_envelope(
    *,
    dataset: str,
    city: City,
    endpoint: str,
    params: dict[str, Any],
    payload: dict[str, Any],
    record_count: int,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "open-meteo",
        "dataset": dataset,
        "city": city.as_dict(),
        "endpoint": endpoint,
        "ingestion_timestamp": utc_now_iso(),
        "run_id": run_id,
        "request_parameters": params,
        "record_count": record_count,
        "backfill": True,
        "response": payload,
    }


def backfill_months(
    store: BronzeStore,
    settings: OpenMeteoSettings,
    *,
    months: Sequence[str],
    locations: Sequence[City],
    prefix: str,
    run_id: str | None = None,
    overwrite: bool = False,
    client: ArchiveClient | None = None,
) -> dict[str, Any]:
    run_id = run_id or new_run_id()
    started = utc_now_iso()
    ingest_date = started[:10]

    own_client = client is None
    archive = client or ArchiveClient(settings)

    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        for month in months:
            for dataset in DATASETS:
                for city in locations:
                    key = object_key(
                        prefix,
                        dataset=dataset,
                        period=month,
                        slug=city.slug,
                    )
                    if not overwrite and store.object_exists(key):
                        entries.append(
                            {
                                "dataset": dataset,
                                "period": month,
                                "city": city.name,
                                "key": key,
                                "action": "skipped",
                                "record_count": 0,
                            }
                        )
                        continue

                    try:
                        payload, params, count = archive.fetch_month(dataset, city, month)
                        envelope = build_envelope(
                            dataset=dataset,
                            city=city,
                            endpoint=(
                                settings.archive_url
                                if dataset == "weather"
                                else settings.air_quality_url
                            ),
                            params=params,
                            payload=payload,
                            record_count=count,
                            run_id=run_id,
                        )
                        store.put_json(
                            key,
                            envelope,
                            metadata={
                                "run-id": run_id,
                                "source": "open-meteo",
                                "dataset": dataset,
                                "period": month,
                                "kind": "backfill",
                            },
                            overwrite=overwrite,
                        )
                        entries.append(
                            {
                                "dataset": dataset,
                                "period": month,
                                "city": city.name,
                                "key": key,
                                "action": "written",
                                "record_count": count,
                            }
                        )
                    except ObjectAlreadyExistsError:
                        entries.append(
                            {
                                "dataset": dataset,
                                "period": month,
                                "city": city.name,
                                "key": key,
                                "action": "skipped",
                                "record_count": 0,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 - isolasi per lokasi
                        failures.append(
                            {
                                "dataset": dataset,
                                "period": month,
                                "city": city.name,
                                "error_type": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                        logger.exception("Gagal backfill %s %s %s", dataset, city.name, month)
    finally:
        if own_client:
            archive.close()

    written = [entry for entry in entries if entry["action"] == "written"]
    manifest = {
        "schema_version": 1,
        "source": "open-meteo-backfill",
        "run_id": run_id,
        "months": list(months),
        "started_at": started,
        "finished_at": utc_now_iso(),
        "status": "partial" if failures and entries else ("failed" if failures else "success"),
        "summary": {
            "objects_expected": len(months) * len(DATASETS) * len(locations),
            "objects_written": len(written),
            "objects_skipped": sum(1 for e in entries if e["action"] == "skipped"),
            "objects_failed": len(failures),
            "records_written": sum(entry["record_count"] for entry in written),
        },
        "entries": entries,
        "failures": failures,
    }
    key = manifest_key(prefix, ingest_date, run_id)
    store.put_json(key, manifest, metadata={"run-id": run_id, "kind": "manifest"})
    return {"manifest_key": key, **manifest["summary"], "status": manifest["status"]}
