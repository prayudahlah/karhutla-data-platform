"""Prefect flow untuk ingest granule MCD64A1 ke Garage Bronze.

Jalankan dari root repo:

    python -m flows.burned_area_ingestion --month 2026-09
    python -m flows.burned_area_ingestion --month 2026-08 --month 2026-09
    python -m flows.burned_area_ingestion --verify-only <run_id>

Tidak ada deployment atau jadwal yang dibuat di sini.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.config import BurnedAreaSettings, load_dotenv  # noqa: E402

load_dotenv(".env")


def _configure_prefect_ephemeral_if_needed() -> None:
    """Pakai API ephemeral kalau pemanggil tidak menyiapkan server Prefect."""

    if os.environ.get("PREFECT_API_URL") or os.environ.get("PREFECT_PROFILES_PATH"):
        return

    profile_dir = Path(tempfile.gettempdir()) / "karhutla-prefect"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profiles = profile_dir / "profiles.toml"
    profiles.write_text(
        'active = "ephemeral"\n\n[profiles.ephemeral]\nPREFECT_SERVER_EPHEMERAL_ENABLED = "true"\n',
        encoding="utf-8",
    )
    os.environ["PREFECT_PROFILES_PATH"] = str(profiles)
    os.environ.setdefault("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "true")


_configure_prefect_ephemeral_if_needed()

from prefect import flow, get_run_logger, task  # noqa: E402

from common.run import new_run_id  # noqa: E402
from common.storage import BronzeStore  # noqa: E402
from ingest.burned_area.ingest import ingest_months, verify_run  # noqa: E402


@task(name="ingest-mcd64a1-bronze", log_prints=True)
def ingest_task(months: list[str], run_id: str) -> dict[str, Any]:
    logger = get_run_logger()
    settings = BurnedAreaSettings.from_env()
    store = BronzeStore(settings.garage)
    store.ensure_bucket()

    manifest, key = ingest_months(
        months,
        settings=settings,
        store=store,
        run_id=run_id,
    )
    logger.info("Manifest: %s", key)
    logger.info("Ringkasan: %s", manifest["summary"])
    return {
        "run_id": run_id,
        "manifest_key": key,
        "status": manifest["status"],
        "summary": manifest["summary"],
        "failures": manifest["failures"],
    }


@flow(name="mcd64a1-bronze", log_prints=True)
def burned_area_ingestion(months: list[str], run_id: str) -> dict[str, Any]:
    result = ingest_task(months, run_id)
    if result["status"] != "success":
        raise RuntimeError(
            f"Ingest MCD64A1 selesai dengan status={result['status']} "
            f"({len(result['failures'])} kegagalan); lihat manifest "
            f"{result['manifest_key']}"
        )
    return result


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
        action="append",
        help="Bulan YYYY-MM; boleh diulang. Wajib kecuali --verify-only.",
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

    if not args.month:
        parser.error("--month wajib diisi minimal satu kali")

    run_id = args.run_id or new_run_id()
    print(f"run_id={run_id} months={','.join(args.month)}")
    result = burned_area_ingestion(args.month, run_id)
    _print_json(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI harus keluar dengan status bukan nol
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
