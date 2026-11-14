"""Unduhan granule dari LP DAAC memakai bearer token Earthdata.

Layanan LP DAAC membalas 303 ke URL CloudFront bertanda tangan. httpx mengikuti
redirect itu, dan header Authorization hanya perlu dikirim ke permintaan pertama.
"""

from __future__ import annotations

import logging
import random
import time

import httpx

from common.config import BurnedAreaSettings
from ingest.burned_area.cmr import BurnedAreaError, Granule

logger = logging.getLogger(__name__)


class MissingTokenError(BurnedAreaError):
    """Token Earthdata belum diisi."""


class DownloadError(BurnedAreaError):
    """Unduhan gagal setelah percobaan ulang."""


class DownloadClient:
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

    def __enter__(self) -> DownloadClient:
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
                delay = min(2**attempt, 60)
        else:
            delay = min(2**attempt, 60)
        delay += random.uniform(0, 0.5)
        logger.warning("Download retry %d in %.1fs", attempt + 1, delay)
        time.sleep(delay)

    def fetch(self, granule: Granule) -> bytes:
        token = self.settings.token.strip()
        if not token:
            raise MissingTokenError(
                "EARTHDATA_TOKEN is empty; fill it in .env atau environment sebelum mengunduh"
            )

        attempts = max(1, self.settings.max_retries)
        headers = {"Authorization": f"Bearer {token}"}
        for attempt in range(attempts):
            try:
                response = self._client.get(granule.url, headers=headers)
            except httpx.HTTPError as exc:
                if attempt + 1 >= attempts:
                    raise DownloadError(
                        f"Download failed after {attempts} attempts: {granule.granule_id}"
                    ) from exc
                self._sleep_before_retry(attempt, None)
                continue

            if response.status_code == 200:
                body = response.content
                if not body:
                    raise DownloadError(f"Empty body for granule {granule.granule_id}")
                logger.info("Downloaded %s (%d bytes)", granule.granule_id, len(body))
                return body

            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < attempts:
                self._sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            raise DownloadError(
                f"Download failed with HTTP {response.status_code} for {granule.granule_id}"
            )
        raise DownloadError(f"Download failed for {granule.granule_id}")
