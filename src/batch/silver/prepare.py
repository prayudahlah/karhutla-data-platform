"""Siapkan folder hasil dbt sebelum ``dbt build`` dijalankan.

DuckDB membuat satu tingkat folder saat menulis parquet dengan ``partition_by``,
tetapi tidak membuat rantai induknya. Modul ini memastikan folder tujuan sudah
ada, supaya ``dbt build`` tidak gagal dengan pesan "Failed to create directory".
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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


def ensure_profiles(project_dir: Path = Path("dbt")) -> Path | None:
    """Salin profiles.yml.example kalau profiles.yml belum ada.

    Tanpa ini, ``task dbt-build`` gagal dengan pesan dbt yang membingungkan
    pada mesin yang baru di-clone.
    """
    target = project_dir / "profiles.yml"
    if target.exists():
        return None
    example = project_dir / "profiles.yml.example"
    if not example.is_file():
        raise FileNotFoundError(f"Contoh profil dbt tidak ditemukan: {example}")
    shutil.copyfile(example, target)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siapkan folder hasil dbt")
    parser.add_argument(
        "--root",
        default=os.environ.get("SILVER_PUBLISH_ROOT", DEFAULT_ROOT),
        help="akar folder hasil dbt",
    )
    args = parser.parse_args(argv)

    created = prepare_publish_root(Path(args.root))
    created_profiles = ensure_profiles()
    print(
        json.dumps(
            {
                "root": args.root,
                "folders": [str(folder) for folder in created],
                "profiles_created": str(created_profiles) if created_profiles else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
