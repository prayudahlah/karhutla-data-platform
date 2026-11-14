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
    ("firms", "hotspot"),
    ("firms", "hotspot_label"),
    ("mcd64a1", "burn_scar"),
    ("mcd64a1", "tiles"),
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


def _assert_safe_clean_target(root: Path) -> Path:
    """Tolak path yang terlalu dangkal.

    Salah ketik pada SILVER_PUBLISH_ROOT bisa berakibat menghapus folder lain,
    jadi pembersihan hanya diizinkan untuk path yang cukup dalam.
    """
    resolved = root.resolve()
    anchor = Path(resolved.anchor)
    if resolved in {anchor, anchor.parent, Path.home()} or len(resolved.parts) < 3:
        raise ValueError(f"Menolak membersihkan path terlalu dangkal: {resolved}")
    return resolved


def clean_publish_root(root: Path) -> int:
    """Kosongkan folder hasil dbt, kembalikan jumlah berkas yang dihapus."""
    resolved = _assert_safe_clean_target(root)
    if not resolved.exists():
        return 0
    removed = sum(1 for path in resolved.rglob("*") if path.is_file())
    shutil.rmtree(resolved)
    return removed


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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="kosongkan folder hasil dulu supaya partisi lama tidak tertinggal",
    )
    args = parser.parse_args(argv)

    removed = clean_publish_root(Path(args.root)) if args.clean else 0
    created = prepare_publish_root(Path(args.root))
    created_profiles = ensure_profiles()
    print(
        json.dumps(
            {
                "root": args.root,
                "folders": [str(folder) for folder in created],
                "files_removed": removed,
                "profiles_created": str(created_profiles) if created_profiles else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
