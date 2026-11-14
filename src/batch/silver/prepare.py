"""Siapkan folder hasil dbt sebelum ``dbt build`` dijalankan.

DuckDB membuat satu tingkat folder saat menulis parquet dengan ``partition_by``,
tetapi tidak membuat rantai induknya. Modul ini memastikan folder tujuan sudah
ada, supaya ``dbt build`` tidak gagal dengan pesan "Failed to create directory".
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

# Daftar ini bertambah setiap ada model Silver baru yang menulis parquet.
PUBLISHED_DATASETS: tuple[tuple[str, str], ...] = (
    ("open_meteo", "weather"),
    ("open_meteo", "air_quality"),
)

DEFAULT_ROOT = "data/silver/published"


def prepare_publish_root(
    root: Path,
    datasets: Sequence[tuple[str, str]] = PUBLISHED_DATASETS,
) -> list[Path]:
    """Buat folder ``<root>/<source>/<dataset>`` dan kembalikan daftarnya."""
    created: list[Path] = []
    for source, dataset in datasets:
        folder = root / source / dataset
        folder.mkdir(parents=True, exist_ok=True)
        created.append(folder)
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siapkan folder hasil dbt")
    parser.add_argument(
        "--root",
        default=os.environ.get("SILVER_PUBLISH_ROOT", DEFAULT_ROOT),
        help="akar folder hasil dbt",
    )
    args = parser.parse_args(argv)

    created = prepare_publish_root(Path(args.root))
    print(json.dumps({"root": args.root, "folders": [str(p) for p in created]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
