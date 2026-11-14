"""Prefect flows untuk ingest granule MCD64A1 ke Garage Bronze.

Jalankan dari root repo:

    python -m flows.burned_area_ingestion --month 2026-09
    python -m flows.burned_area_ingestion            # bulan terbaru dari CMR
    python -m flows.burned_area_ingestion --verify-only <run_id>

Flow dipecah menjadi tiga task supaya grafiknya terlihat di UI Prefect:

    list-granules -> fetch-granule (dipetakan per granule) -> write-manifest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.config import BurnedAreaSettings, Settings, load_dotenv  # noqa: E402

load_dotenv(".env")


def _configure_prefect_ephemeral_if_needed() -> None:
    """Pakai API ephemeral kalau pemanggil tidak menyiapkan server Prefect."""

    if os.environ.get("PREFECT_API_URL") or os.environ.get("PREFECT_PROFILES_PATH"):
        return

    profile_dir = Path(tempfile.gettempdir()) / "karhutla-prefect"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profiles = profile_dir / "profiles.toml"
    profiles.write_text(
        'active = "ephemeral"\n\n'
        "[profiles.ephemeral]\n"
        'PREFECT_SERVER_EPHEMERAL_ENABLED = "true"\n',
        encoding="utf-8",
    )
    os.environ["PREFECT_PROFILES_PATH"] = str(profiles)
    os.environ.setdefault("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "true")


_configure_prefect_ephemeral_if_needed()

from prefect import flow, get_run_logger, task, unmapped  # noqa: E402

from common.run import new_run_id, utc_now_iso  # noqa: E402
from common.storage import BronzeStore  # noqa: E402
from ingest.burned_area.cmr import CmrClient, Granule  # noqa: E402
from ingest.burned_area.download import DownloadClient  # noqa: E402
from ingest.burned_area.ingest import (  # noqa: E402
    GranuleFailure,
    build_manifest,
    ingest_granules,
    manifest_key,
    verify_run,
)


@task(name="list-granules", retries=2, retry_delay_seconds=30, log_prints=True)
def list_granules_task(month: str) -> list[dict[str, Any]]:
    settings = BurnedAreaSettings.from_env()
    with CmrClient(settings) as cmr:
        granules = cmr.search_month(month)
    get_run_logger().info("%d granule untuk %s", len(granules), month)
    return [asdict(granule) for granule in granules]


@task(name="fetch-granule", retries=3, retry_delay_seconds=60, log_prints=True)
def fetch_granule_task(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Unduh satu granule dan tulis ke Bronze.

    Dipanggil lewat ``.map`` sehingga tiap granule punya cabangnya sendiri di UI.
    """
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)
    granule = Granule(**payload)
    with DownloadClient(settings.burned_area) as downloader:
        entries, failures = ingest_granules(
            [granule],
            downloader=downloader,
            store=store,
            run_id=run_id,
            prefix=settings.burned_area.bronze_prefix,
        )
    return {
        "entries": entries,
        "failures": [asdict(failure) for failure in failures],
    }


@task(name="write-manifest", log_prints=True)
def write_manifest_task(
    months: list[str],
    entries: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    run_id: str,
    started_at: str,
) -> dict[str, Any]:
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)
    manifest = build_manifest(
        months=months,
        entries=entries,
        failures=[GranuleFailure(**failure) for failure in failures],
        settings=settings.burned_area,
        run_id=run_id,
        started_at=started_at,
        finished_at=utc_now_iso(),
    )
    key = manifest_key(settings.burned_area.bronze_prefix, run_id)
    store.put_json(
        key,
        manifest,
        metadata={"run-id": run_id, "source": "mcd64a1", "kind": "manifest"},
    )
    get_run_logger().info("Manifest: %s (%s)", key, manifest["status"])
    return {
        "run_id": run_id,
        "manifest_key": key,
        "status": manifest["status"],
        "summary": manifest["summary"],
        "failures": manifest["failures"],
    }


@flow(name="mcd64a1-bronze", log_prints=True)
def burned_area_ingestion(months: list[str], run_id: str) -> dict[str, Any]:
    started_at = utc_now_iso()
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for month in months:
        granules = list_granules_task(month)
        if not granules:
            failures.append(
                {
                    "granule_id": f"month={month}",
                    "tile": "",
                    "error_type": "NoGranules",
                    "message": f"CMR tidak mengembalikan granule untuk {month}",
                }
            )
            continue

        futures = fetch_granule_task.map(granules, unmapped(run_id))
        for future in futures:
            result = future.result()
            entries.extend(result["entries"])
            failures.extend(result["failures"])

    result = write_manifest_task(months, entries, failures, run_id, started_at)
    if result["status"] != "success":
        raise RuntimeError(
            f"Ingest MCD64A1 selesai dengan status={result['status']} "
            f"({len(result['failures'])} kegagalan); lihat manifest {result['manifest_key']}"
        )
    return result


@flow(name="mcd64a1-bronze-monthly", log_prints=True)
def monthly_ingestion(month: str | None = None) -> dict[str, Any]:
    """Entrypoint untuk deployment terjadwal.

    Kalau ``month`` kosong, bulan diambil dari CMR supaya lag rilis produk tidak
    perlu ditebak.
    """
    if month is None:
        settings = BurnedAreaSettings.from_env()
        with CmrClient(settings) as cmr:
            month = cmr.latest_month()
        if month is None:
            raise RuntimeError("CMR tidak mengembalikan granule MCD64A1 untuk bbox ini")
        get_run_logger().info("Bulan terbaru dari CMR: %s", month)
    return burned_area_ingestion([month], new_run_id())


def verify(run_id: str) -> dict[str, Any]:
    settings = BurnedAreaSettings.from_env()
    store = BronzeStore(settings.garage)
    return verify_run(store, run_id, prefix=settings.bronze_prefix)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCD64A1 ke Garage Bronze")
    parser.add_argument(
        "--month",
        help="Bulan YYYY-MM. Kosongkan untuk memakai bulan terbaru dari CMR.",
    )
    parser.add_argument("--run-id", help="Run id eksplisit; default dibuat otomatis")
    parser.add_argument(
        "--verify-only",
        metavar="RUN_ID",
        help="Baca ulang manifest dan objeknya tanpa mengunduh lagi",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        result = verify(args.verify_only)
        _print_json(result)
        return 0 if result["ok"] else 1

    run_id = args.run_id or new_run_id()
    if args.month:
        print(f"run_id={run_id} month={args.month}")
        result = burned_area_ingestion([args.month], run_id)
    else:
        print(f"run_id={run_id} month=<terbaru>")
        result = monthly_ingestion(None)
    _print_json(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI harus keluar dengan status bukan nol
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
