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

# Daftar ini bertambah setiap ada model yang menulis parquet.
PUBLISHED_DATASETS: tuple[tuple[str, ...], ...] = (
    ("open_meteo", "weather"),
    ("open_meteo", "air_quality"),
    ("firms", "hotspot"),
    ("firms", "hotspot_label"),
    ("mcd64a1", "burn_scar"),
    ("mcd64a1", "tiles"),
)

# Gold: tabel yang ditulis dbt. Folder ini dibersihkan sebelum build supaya
# partisi lama tidak tertinggal (materialization external menulis ulang semua).
GOLD_DB_TABLES: tuple[tuple[str, ...], ...] = (
    ("cell_daily",),
    ("province_daily",),
    ("burn_scar_monthly",),
)

# Gold: tabel yang ditulis proses lain (inference ML), jadi tidak ikut dibersihkan.
GOLD_EXTERNAL_TABLES: tuple[tuple[str, ...], ...] = (("risk_prediction_daily",),)

GOLD_DATASETS: tuple[tuple[str, ...], ...] = GOLD_DB_TABLES + GOLD_EXTERNAL_TABLES

DEFAULT_SILVER_ROOT = "data/silver/published"
DEFAULT_GOLD_ROOT = "data/gold/published"

LAYER_DATASETS: dict[str, tuple[tuple[str, ...], ...]] = {
    "silver": PUBLISHED_DATASETS,
    "gold": GOLD_DATASETS,
}

# Hanya folder ini yang boleh dikosongkan oleh --clean. ``None`` berarti
# seluruh akar layer dibersihkan; Gold dibatasi agar output ML tidak terhapus.
LAYER_DB_DATASETS: dict[str, tuple[tuple[str, ...], ...] | None] = {
    "silver": None,
    "gold": GOLD_DB_TABLES,
}


def datasets_for_layer(layer: str) -> tuple[tuple[str, ...], ...]:
    """Kembalikan daftar folder untuk satu layer."""
    try:
        return LAYER_DATASETS[layer]
    except KeyError as exc:  # pragma: no cover - argparse sudah membatasi pilihan
        raise ValueError(f"Layer tidak dikenal: {layer}") from exc


def default_root_for_layer(layer: str) -> str:
    """Akar folder hasil dbt untuk satu layer, bisa dioverride lewat env."""
    if layer == "gold":
        return os.environ.get("GOLD_PUBLISH_ROOT", DEFAULT_GOLD_ROOT)
    return os.environ.get("SILVER_PUBLISH_ROOT", DEFAULT_SILVER_ROOT)


def prepare_publish_root(
    root: Path,
    datasets: Sequence[Sequence[str]] = PUBLISHED_DATASETS,
) -> list[Path]:
    """Buat folder ``<root>/<part...>`` dan kembalikan daftarnya."""
    created: list[Path] = []
    for parts in datasets:
        folder = root.joinpath(*parts)
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


def clean_publish_root(
    root: Path,
    datasets: Sequence[Sequence[str]] | None = None,
) -> int:
    """Kosongkan folder hasil dbt, kembalikan jumlah berkas yang dihapus.

    ``datasets`` membatasi pembersihan ke folder tertentu. Tanpa argumen,
    seluruh ``root`` dikosongkan.
    """
    resolved = _assert_safe_clean_target(root)
    if not resolved.exists():
        return 0
    targets = (
        [resolved.joinpath(*parts) for parts in datasets]
        if datasets is not None
        else [resolved]
    )
    removed = 0
    for target in targets:
        if target.is_dir():
            removed += sum(1 for path in target.rglob("*") if path.is_file())
            shutil.rmtree(target)
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


def prepare_layer(
    layer: str,
    root: Path | None = None,
    clean: bool = False,
) -> dict[str, object]:
    """Siapkan satu layer: bersihkan (opsional) lalu buat foldernya."""
    root_path = root or Path(default_root_for_layer(layer))
    removed = (
        clean_publish_root(root_path, LAYER_DB_DATASETS[layer]) if clean else 0
    )
    created = prepare_publish_root(root_path, datasets_for_layer(layer))
    return {
        "layer": layer,
        "root": str(root_path),
        "folders": [str(folder) for folder in created],
        "files_removed": removed,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siapkan folder hasil dbt")
    parser.add_argument(
        "--layer",
        choices=["all", *sorted(LAYER_DATASETS)],
        default="all",
        help="layer yang disiapkan (default: all)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="akar folder hasil dbt, hanya bisa dipakai dengan satu layer",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="kosongkan folder hasil dulu supaya partisi lama tidak tertinggal",
    )
    args = parser.parse_args(argv)

    layers = sorted(LAYER_DATASETS) if args.layer == "all" else [args.layer]
    if args.root and len(layers) > 1:
        parser.error("--root hanya bisa dipakai bersama satu --layer")

    results = [
        prepare_layer(layer, Path(args.root) if args.root else None, args.clean)
        for layer in layers
    ]
    created_profiles = ensure_profiles()
    print(
        json.dumps(
            {
                "layers": results,
                "profiles_created": str(created_profiles) if created_profiles else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
