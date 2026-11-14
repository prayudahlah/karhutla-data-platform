"""Pencarian granule MCD64A1 lewat CMR.

CMR tidak butuh autentikasi. Yang butuh token Earthdata hanya unduhannya, jadi
pencarian dan pengunduhan dipisah ke dua modul.
"""

from __future__ import annotations

import calendar
import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from common.config import BurnedAreaSettings

logger = logging.getLogger(__name__)


class BurnedAreaError(RuntimeError):
    """Kesalahan dasar modul burned area."""


class CmrError(BurnedAreaError):
    """CMR tidak bisa dihubungi, atau balasannya tidak sesuai bentuk yang diharapkan."""


@dataclass(frozen=True)
class Granule:
    granule_id: str
    month: str
    tile: str
    size_bytes: int
    url: str

    @property
    def filename(self) -> str:
        return f"{self.granule_id}.hdf"


def parse_month(value: str) -> date:
    """Validasi 'YYYY-MM' dan kembalikan tanggal pertama bulan itu."""
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"Month must look like YYYY-MM, got {value!r}") from exc
    return parsed.date().replace(day=1)


def month_window(value: str) -> tuple[str, str]:
    """Batas waktu ISO untuk satu bulan, dipakai sebagai parameter temporal CMR."""
    start = parse_month(value)
    last_day = calendar.monthrange(start.year, start.month)[1]
    end = date(start.year, start.month, last_day)
    return (
        f"{start.isoformat()}T00:00:00Z",
        f"{end.isoformat()}T23:59:59Z",
    )


def granule_id_to_month(granule_id: str) -> str:
    """Ubah AYYYYDDD di dalam granule id menjadi YYYY-MM.

    Hari di granule id adalah hari pertama bulan yang dicakup produk, misalnya
    A2026244 berarti 1 September 2026.
    """
    parts = granule_id.split(".")
    if len(parts) < 3 or not parts[1].startswith("A") or len(parts[1]) != 8:
        raise CmrError(f"Unexpected granule id: {granule_id!r}")
    try:
        day = datetime.strptime(parts[1][1:], "%Y%j").date()
    except ValueError as exc:
        raise CmrError(f"Granule id has an invalid date: {granule_id!r}") from exc
    return day.strftime("%Y-%m")


def granule_from_entry(entry: dict) -> Granule:
    granule_id = str(entry.get("title", "")).strip()
    urls = [
        str(link.get("href", ""))
        for link in entry.get("links", [])
        if str(link.get("href", "")).endswith(".hdf")
    ]
    if not granule_id or not urls:
        raise CmrError(f"Granule entry has no id or .hdf link: {entry.get('title')!r}")
    return Granule(
        granule_id=granule_id,
        month=granule_id_to_month(granule_id),
        tile=granule_id.split(".")[2],
        size_bytes=int(float(entry.get("granule_size", 0) or 0)),
        url=urls[0],
    )


class CmrClient:
    """Klien tipis untuk endpoint granule CMR."""

    def __init__(
        self,
        settings: BurnedAreaSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "karhutla-data-platform/0.1 (+burned-area)"},
        )

    def __enter__(self) -> CmrClient:
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
        logger.warning("CMR retry %d in %.1fs", attempt + 1, delay)
        time.sleep(delay)

    def _get_json(self, params: dict) -> dict:
        attempts = max(1, self.settings.max_retries)
        for attempt in range(attempts):
            try:
                response = self._client.get(self.settings.cmr_url, params=params)
            except httpx.HTTPError as exc:
                if attempt + 1 >= attempts:
                    raise CmrError(f"CMR request failed after {attempts} attempts: {exc}") from exc
                self._sleep_before_retry(attempt, None)
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise CmrError("CMR returned a non-JSON response") from exc
                if not isinstance(payload, dict):
                    raise CmrError("CMR returned an unexpected JSON type")
                return payload

            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if retryable and attempt + 1 < attempts:
                self._sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            raise CmrError(
                f"CMR request failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        raise CmrError("CMR request failed")

    def latest_month(self) -> str | None:
        """Bulan terbaru yang sudah tersedia di CMR untuk bbox ini.

        Dipakai penjadwalan bulanan, supaya tidak menebak lag rilis produk.
        """
        bbox = ",".join(f"{value:g}" for value in self.settings.bbox)
        params: dict = {
            "short_name": self.settings.short_name,
            "version": self.settings.version,
            "bounding_box": bbox,
            "page_size": 5,
            "sort_key": "-start_date",
        }
        payload = self._get_json(params)
        feed = payload.get("feed")
        if not isinstance(feed, dict):
            raise CmrError("CMR response has no 'feed' object")
        entries = feed.get("entry") or []
        if not entries:
            return None
        return granule_id_to_month(str(entries[0].get("title", "")))

    def search_month(self, month: str) -> list[Granule]:
        """Cari semua granule yang menyentuh bbox untuk satu bulan."""
        start, end = month_window(month)
        bbox = ",".join(f"{value:g}" for value in self.settings.bbox)
        params: dict = {
            "short_name": self.settings.short_name,
            "version": self.settings.version,
            "bounding_box": bbox,
            "temporal": f"{start},{end}",
            "page_size": self.settings.page_size,
            "page_num": 1,
        }

        granule_list: list[Granule] = []
        while True:
            payload = self._get_json(params)
            feed = payload.get("feed")
            if not isinstance(feed, dict):
                raise CmrError("CMR response has no 'feed' object")
            entries = feed.get("entry", [])
            if not isinstance(entries, list):
                raise CmrError("CMR response has a non-list 'feed.entry'")

            for entry in entries:
                granule = granule_from_entry(entry)
                if granule.month == month:
                    granule_list.append(granule)

            if len(entries) < self.settings.page_size:
                break
            params = {**params, "page_num": int(params["page_num"]) + 1}

        granule_list.sort(key=lambda item: (item.tile, item.granule_id))
        logger.info("CMR returned %d granule for %s", len(granule_list), month)
        return granule_list
