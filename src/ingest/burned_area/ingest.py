"""Orkestrasi ingest MCD64A1 ke Bronze, plus manifest dan verifikasi."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from common.config import BurnedAreaSettings
from common.run import run_date_from_run_id, utc_now_iso
from common.storage import BronzeStorageError, BronzeStore, ObjectNotFoundError, sha256_hex
from ingest.burned_area.cmr import CmrClient, Granule
from ingest.burned_area.download import DownloadClient

logger = logging.getLogger(__name__)

CONTENT_TYPE_HDF = "application/x-hdf"

# Tindakan yang mungkin tercatat di manifest.
ACTION_WRITTEN = "written"
ACTION_SKIPPED = "skipped"
ACTION_FAILED = "failed"


@dataclass(frozen=True)
class GranuleFailure:
    granule_id: str
    tile: str
    error_type: str
    message: str


def object_key(prefix: str, granule: Granule) -> str:
    """Kunci Bronze memakai identitas granule, bukan run_id.

    Granule tidak pernah berubah, jadi mengunduh ulang bulan yang sama tidak
    boleh menghasilkan duplikat dengan nama berbeda.
    """
    return f"{prefix.strip('/')}/month={granule.month}/tile={granule.tile}/{granule.filename}"


def manifest_key(prefix: str, run_id: str) -> str:
    ingest_date = run_date_from_run_id(run_id)
    return f"{prefix.strip('/')}/manifests/ingest_date={ingest_date}/run_id={run_id}.json"


def config_snapshot(settings: BurnedAreaSettings) -> dict[str, Any]:
    """Potret konfigurasi tanpa token."""
    return {
        "cmr_url": settings.cmr_url,
        "short_name": settings.short_name,
        "version": settings.version,
        "bronze_prefix": settings.bronze_prefix,
        "bbox": list(settings.bbox),
        "has_token": bool(settings.token.strip()),
    }


def ingest_granules(
    granules: Sequence[Granule],
    *,
    downloader: DownloadClient,
    store: BronzeStore,
    run_id: str,
    prefix: str,
    overwrite: bool = False,
) -> tuple[list[dict[str, Any]], list[GranuleFailure]]:
    entries: list[dict[str, Any]] = []
    failures: list[GranuleFailure] = []

    for index, granule in enumerate(granules, start=1):
        key = object_key(prefix, granule)
        logger.info("[%d/%d] %s", index, len(granules), granule.granule_id)

        if not overwrite and store.object_exists(key):
            logger.info("Sudah ada, dilewati: s3://%s/%s", store.bucket, key)
            entries.append(
                {
                    "granule_id": granule.granule_id,
                    "month": granule.month,
                    "tile": granule.tile,
                    "key": key,
                    "action": ACTION_SKIPPED,
                    "size_bytes": granule.size_bytes,
                }
            )
            continue

        try:
            body = downloader.fetch(granule)
            digest = store.put_bytes(
                key,
                body,
                content_type=CONTENT_TYPE_HDF,
                metadata={
                    "run-id": run_id,
                    "source": "mcd64a1",
                    "month": granule.month,
                    "tile": granule.tile,
                    "granule-id": granule.granule_id,
                },
                overwrite=overwrite,
            )
            head = store.head_object(key)
            entries.append(
                {
                    "granule_id": granule.granule_id,
                    "month": granule.month,
                    "tile": granule.tile,
                    "key": key,
                    "action": ACTION_WRITTEN,
                    "size_bytes": int(head.get("ContentLength", len(body))),
                    "sha256": digest,
                }
            )
        except Exception as exc:  # noqa: BLE001 - isolasi per granule disengaja
            failures.append(
                GranuleFailure(
                    granule_id=granule.granule_id,
                    tile=granule.tile,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            logger.exception("Gagal mengunduh %s", granule.granule_id)

    return entries, failures


def build_manifest(
    *,
    months: Sequence[str],
    entries: Sequence[dict[str, Any]],
    failures: Sequence[GranuleFailure],
    settings: BurnedAreaSettings,
    run_id: str,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    written = sum(1 for entry in entries if entry["action"] == ACTION_WRITTEN)
    skipped = sum(1 for entry in entries if entry["action"] == ACTION_SKIPPED)
    if failures and entries:
        status = "partial"
    elif failures:
        status = "failed"
    else:
        status = "success"

    return {
        "schema_version": 1,
        "source": "mcd64a1",
        "product": f"{settings.short_name} v{settings.version}",
        "run_id": run_id,
        "status": status,
        "months": list(months),
        "started_at": started_at,
        "finished_at": finished_at,
        "config": config_snapshot(settings),
        "summary": {
            "granules_seen": len(entries) + len(failures),
            "granules_written": written,
            "granules_skipped": skipped,
            "granules_failed": len(failures),
            "bytes_written": sum(
                int(entry.get("size_bytes", 0))
                for entry in entries
                if entry["action"] == ACTION_WRITTEN
            ),
        },
        "entries": list(entries),
        "failures": [
            {
                "granule_id": failure.granule_id,
                "tile": failure.tile,
                "error_type": failure.error_type,
                "message": failure.message,
            }
            for failure in failures
        ],
    }


def ingest_months(
    months: Sequence[str],
    *,
    settings: BurnedAreaSettings,
    store: BronzeStore,
    run_id: str,
    cmr: CmrClient | None = None,
    downloader: DownloadClient | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], str]:
    started_at = utc_now_iso()
    entries: list[dict[str, Any]] = []
    failures: list[GranuleFailure] = []

    own_cmr = cmr is None
    own_downloader = downloader is None
    cmr_client = cmr or CmrClient(settings)
    download_client = downloader or DownloadClient(settings)

    try:
        for month in months:
            granules = cmr_client.search_month(month)
            if not granules:
                failures.append(
                    GranuleFailure(
                        granule_id=f"month={month}",
                        tile="",
                        error_type="NoGranules",
                        message=f"CMR tidak mengembalikan granule untuk {month}",
                    )
                )
                continue
            month_entries, month_failures = ingest_granules(
                granules,
                downloader=download_client,
                store=store,
                run_id=run_id,
                prefix=settings.bronze_prefix,
                overwrite=overwrite,
            )
            entries.extend(month_entries)
            failures.extend(month_failures)
    finally:
        if own_cmr:
            cmr_client.close()
        if own_downloader:
            download_client.close()

    finished_at = utc_now_iso()
    manifest = build_manifest(
        months=months,
        entries=entries,
        failures=failures,
        settings=settings,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
    )
    key = manifest_key(settings.bronze_prefix, run_id)
    store.put_json(
        key,
        manifest,
        metadata={"run-id": run_id, "source": "mcd64a1", "kind": "manifest"},
    )
    logger.info("Manifest: s3://%s/%s (status=%s)", store.bucket, key, manifest["status"])
    return manifest, key


def verify_run(store: BronzeStore, run_id: str, *, prefix: str) -> dict[str, Any]:
    key = manifest_key(prefix, run_id)
    if not store.object_exists(key):
        raise ObjectNotFoundError(f"Manifest for run_id {run_id!r} not found: {key}")

    manifest = store.read_json(key)
    verified: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for entry in manifest.get("entries", []):
        if entry.get("action") == ACTION_SKIPPED:
            continue
        object_key_value = entry.get("key", "")
        try:
            body = store.read_bytes(object_key_value)
            digest = sha256_hex(body)
            if digest != entry.get("sha256"):
                raise BronzeStorageError(
                    f"Checksum mismatch for {object_key_value}: "
                    f"expected {entry.get('sha256')}, got {digest}"
                )
            verified.append(
                {
                    "key": object_key_value,
                    "granule_id": entry.get("granule_id"),
                    "size_bytes": len(body),
                    "sha256": digest,
                }
            )
        except Exception as exc:  # noqa: BLE001 - kumpulkan semua kegagalan baca
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
        "objects_expected": sum(
            1 for entry in manifest.get("entries", []) if entry.get("action") == ACTION_WRITTEN
        ),
        "objects_verified": len(verified),
        "bytes_verified": sum(item["size_bytes"] for item in verified),
        "ok": not failures,
        "verified": verified,
        "failures": failures,
    }


def load_manifest(store: BronzeStore, run_id: str, *, prefix: str) -> dict[str, Any]:
    key = manifest_key(prefix, run_id)
    if not store.object_exists(key):
        raise ObjectNotFoundError(f"Manifest for run_id {run_id!r} not found: {key}")
    payload = store.read_json(key)
    if not isinstance(payload, dict):
        raise BronzeStorageError(f"Manifest {key} bukan objek JSON")
    return payload


def summarize_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest.get("summary", {}), ensure_ascii=False)
