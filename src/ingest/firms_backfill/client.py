"""Klien area API FIRMS untuk hotspot historis.

API ini membatasi satu permintaan maksimal 5 hari untuk sumber NRT, jadi satu
bulan diambil dalam beberapa jendela.
"""

from __future__ import annotations

import csv
import io
import logging
import random
import time
from datetime import date, timedelta
from typing import Any

import httpx

from common.config import FirmsBackfillSettings

logger = logging.getLogger(__name__)

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"


class FirmsBackfillError(RuntimeError):
    """Panggilan API gagal, atau balasannya tidak berbentuk CSV."""


class MissingMapKeyError(FirmsBackfillError):
    """MAP_KEY belum diisi."""


def month_windows(month: str, days: int = 5) -> list[tuple[date, date]]:
    """Pecah satu bulan menjadi jendela maksimal ``days`` hari."""
    start = date.fromisoformat(f"{month}-01")
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    windows: list[tuple[date, date]] = []
    current = start
    while current < end:
        last = min(current + timedelta(days=days - 1), end - timedelta(days=1))
        windows.append((current, last))
        current = last + timedelta(days=1)
    return windows


class FirmsAreaClient:
    def __init__(
        self,
        settings: FirmsBackfillSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "karhutla-data-platform/0.1 (+firms-backfill)"},
        )

    def __enter__(self) -> FirmsAreaClient:
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
        logger.warning("FIRMS retry %d in %.1fs", attempt + 1, delay)
        time.sleep(delay)

    def fetch_window(self, source: str, start: date, days: int) -> list[dict[str, Any]]:
        key = self.settings.map_key.strip()
        if not key:
            raise MissingMapKeyError(
                "FIRMS_MAP_KEY kosong; isi di .env sebelum menjalankan backfill"
            )

        bbox = ",".join(f"{value:g}" for value in self.settings.bbox)
        url = f"{BASE_URL}/{key}/{source}/{bbox}/{days}/{start.isoformat()}"
        attempts = max(1, self.settings.max_retries)
        headers = {"User-Agent": "karhutla-data-platform/0.1 (+firms-backfill)"}

        for attempt in range(attempts):
            try:
                response = self._client.get(url, headers=headers)
            except httpx.HTTPError:
                if attempt + 1 >= attempts:
                    raise FirmsBackfillError(
                        f"Permintaan gagal setelah {attempts} percobaan ({source}, {start})"
                    ) from None
                self._sleep_before_retry(attempt, None)
                continue

            if response.status_code == 200:
                body = response.text
                if "latitude" not in body[:300]:
                    raise FirmsBackfillError(f"Balasan {source} {start} bukan CSV: {body[:120]!r}")
                return list(csv.DictReader(io.StringIO(body)))

            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < attempts:
                self._sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            raise FirmsBackfillError(f"HTTP {response.status_code} untuk {source} {start}")
        raise FirmsBackfillError(f"Permintaan gagal untuk {source} {start}")
