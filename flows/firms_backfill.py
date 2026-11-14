"""Backfill hotspot FIRMS historis ke Garage Bronze.

Contoh:

    python -m flows.firms_backfill --month 2026-09
    python -m flows.firms_backfill --month 2026-08 --source MODIS_NRT
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.config import Settings, load_dotenv  # noqa: E402
from common.storage import BronzeStore  # noqa: E402
from ingest.firms_backfill.ingest import backfill_month  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Backfill hotspot FIRMS ke Bronze")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument(
        "--source",
        action="append",
        help="Batasi ke satu sumber; boleh diulang. Default semua sumber.",
    )
    parser.add_argument("--run-id", help="Run id eksplisit; default dibuat otomatis")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Timpa objek yang sudah ada",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.source:
        settings = Settings(
            garage=settings.garage,
            openmeteo=settings.openmeteo,
            firms_bronze=settings.firms_bronze,
            burned_area=settings.burned_area,
            firms_backfill=type(settings.firms_backfill)(
                map_key=settings.firms_backfill.map_key,
                bbox=settings.firms_backfill.bbox,
                sources=tuple(args.source),
                window_days=settings.firms_backfill.window_days,
                timeout_seconds=settings.firms_backfill.timeout_seconds,
                max_retries=settings.firms_backfill.max_retries,
            ),
        )

    store = BronzeStore(settings.garage)
    result = backfill_month(
        store,
        settings.firms_backfill,
        month=args.month,
        prefix=settings.firms_bronze.prefix,
        run_id=args.run_id,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
