"""Backfill cuaca dan kualitas udara Open-Meteo ke Garage Bronze.

Contoh:

    python -m flows.openmeteo_backfill --month 2026-09
    python -m flows.openmeteo_backfill --month 2026-08 --month 2026-09
    python -m flows.openmeteo_backfill --month 2026-09 --locations city --limit 5
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
from ingest.openmeteo.backfill import backfill_months  # noqa: E402
from ingest.openmeteo.locations import load_cities  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Backfill Open-Meteo ke Bronze")
    parser.add_argument("--month", action="append", required=True, help="YYYY-MM")
    parser.add_argument(
        "--locations",
        choices=["province", "city"],
        default=None,
        help="Default mengikuti OPENMETEO_LOCATION_LEVEL",
    )
    parser.add_argument("--limit", type=int, help="Batasi jumlah lokasi")
    parser.add_argument("--run-id", help="Run id eksplisit")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    location_level = args.locations or settings.openmeteo.location_level
    csv_path = (
        settings.openmeteo.provinces_csv
        if location_level == "province"
        else settings.openmeteo.city_csv
    )
    locations = load_cities(csv_path, limit=args.limit)

    store = BronzeStore(settings.garage)
    result = backfill_months(
        store,
        settings.openmeteo,
        months=args.month,
        locations=locations,
        prefix=settings.garage.prefix,
        run_id=args.run_id,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
