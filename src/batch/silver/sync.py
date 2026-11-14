"""Salin parquet antara Garage dan folder kerja lokal.

dbt membaca dan menulis di filesystem lokal, sedangkan sumber dan tujuan
sebenarnya ada di Garage. Modul ini jembatannya:

    pull : silver/_normalized/**  ->  data/silver/_normalized/**
    push : data/silver/published/**  ->  silver/<source>/dataset=<dataset>/**

Tanpa ``pull``, dbt hanya akan membaca fixture. Tanpa ``push``, tabel final
tidak pernah sampai ke object storage.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa

from batch.silver.parquet import (
    PARQUET_CONTENT_TYPE,
    ObjectStore,
    parquet_bytes,
    upload_parquet,
)
from common.config import Settings
from common.storage import BronzeStore

NORMALIZED_PREFIX = "silver/_normalized"
SILVER_PREFIX = "silver"


class SyncError(RuntimeError):
    """Folder atau kunci tidak sesuai bentuk yang diharapkan."""


def mirror_path(local_root: Path, key: str) -> Path:
    """Petakan kunci Silver ke path lokal, membuang akar ``silver/``."""
    for prefix in (NORMALIZED_PREFIX, SILVER_PREFIX):
        if key.startswith(f"{prefix}/"):
            return local_root / key[len(prefix) + 1 :]
    raise SyncError(f"Kunci tidak berada di bawah {SILVER_PREFIX}: {key}")


def publish_table(
    store: ObjectStore,
    key: str,
    table: pa.Table,
    *,
    local_root: Path | None = None,
    metadata: dict[str, str] | None = None,
    overwrite: bool = False,
) -> str:
    """Tulis ke Garage, dan opsional ke salinan lokal untuk dbt.

    Dua normalizer sebelumnya berbeda: satu menulis lokal lalu push, yang lain
    hanya ke Garage. Fungsi ini menyatukan keduanya: object storage selalu
    menjadi tujuan utama, salinan lokal hanya untuk kenyamanan dbt.
    """
    digest = upload_parquet(store, key, table, metadata=metadata, overwrite=overwrite)
    if local_root is not None:
        destination = mirror_path(local_root, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(parquet_bytes(table))
    return digest


def pull(
    store: ObjectStore,
    *,
    local_root: Path,
    source: str | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    """Unduh parquet normalized dari Garage ke folder kerja lokal."""
    keys = [key for key in store.list_keys(f"{NORMALIZED_PREFIX}/") if key.endswith(".parquet")]
    if source:
        keys = [key for key in keys if f"/{source}/dataset=" in key]
    if month:
        keys = [key for key in keys if f"date={month}-" in key]
    if not keys:
        raise SyncError(
            f"Tidak ada parquet di {NORMALIZED_PREFIX}"
            + (f" untuk source={source}" if source else "")
            + (f" bulan={month}" if month else "")
        )

    downloaded = 0
    skipped = 0
    total_bytes = 0
    for key in keys:
        relative = key[len(NORMALIZED_PREFIX) + 1 :]
        destination = local_root / relative
        body = store.read_bytes(key)
        total_bytes += len(body)
        if destination.exists() and destination.read_bytes() == body:
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        downloaded += 1

    return {
        "keys": len(keys),
        "downloaded": downloaded,
        "skipped": skipped,
        "bytes": total_bytes,
        "local_root": str(local_root),
    }


def push(
    store: ObjectStore,
    *,
    local_root: Path,
    source: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Unggah parquet hasil dbt ke Silver di Garage."""
    if not local_root.is_dir():
        raise SyncError(f"Folder hasil dbt tidak ada: {local_root}")

    files = sorted(local_root.rglob("*.parquet"))
    if not files:
        raise SyncError(f"Tidak ada parquet di {local_root}")

    uploaded = 0
    total_bytes = 0
    for path in files:
        relative = path.relative_to(local_root)
        parts = relative.parts
        if len(parts) < 3:
            raise SyncError(
                f"Path hasil dbt harus <source>/<dataset>/<partisi>/<berkas>: {relative}"
            )
        file_source, dataset, *rest = parts
        if source and file_source != source:
            continue
        key = f"{SILVER_PREFIX}/{file_source}/dataset={dataset}/" + "/".join(rest)
        body = path.read_bytes()
        store.put_bytes(
            key,
            body,
            content_type=PARQUET_CONTENT_TYPE,
            metadata={
                "kind": "silver-parquet",
                "source": file_source,
                "dataset": dataset,
            },
            overwrite=overwrite,
        )
        uploaded += 1
        total_bytes += len(body)

    return {
        "files": len(files),
        "uploaded": uploaded,
        "bytes": total_bytes,
        "local_root": str(local_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sinkronisasi parquet Silver")
    sub = parser.add_subparsers(dest="command", required=True)

    pull_parser = sub.add_parser("pull", help="Garage ke lokal")
    pull_parser.add_argument("--source", help="hanya satu sumber, mis. mcd64a1")
    pull_parser.add_argument("--month", help="hanya satu bulan, format YYYY-MM")
    pull_parser.add_argument(
        "--local-root", default="data/silver/_normalized", help="folder tujuan"
    )

    push_parser = sub.add_parser("push", help="lokal ke Garage")
    push_parser.add_argument("--source", help="hanya satu sumber")
    push_parser.add_argument(
        "--local-root", default="data/silver/published", help="folder hasil dbt"
    )
    push_parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="gagal kalau objek sudah ada, bukan menimpanya",
    )

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)

    if args.command == "pull":
        result = pull(
            store,
            local_root=Path(args.local_root),
            source=args.source,
            month=args.month,
        )
    else:
        result = push(
            store,
            local_root=Path(args.local_root),
            source=args.source,
            overwrite=not args.no_overwrite,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
