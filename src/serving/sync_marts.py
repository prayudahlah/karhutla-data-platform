"""Salin tiga mart Gold dari Iceberg ke Postgres.

Sumbernya snapshot Iceberg aktif (``current.json``), bukan Parquet. DuckDB
membaca Arrow hasil scan pyiceberg lalu menulis lewat extension ``postgres``.

Contoh::

    $env:DATABASE_DSN = "dbname=karhutla user=karhutla password=rahasia host=localhost port=5432"
    python -m serving.sync_marts
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

import duckdb

from batch.gold.publish import NAMESPACE, load_catalog

ICEBERG_ROOT = Path(os.environ.get("ICEBERG_ROOT", "data/gold/_iceberg"))

# Nama tabel di Postgres -> nama tabel Gold.
MART_TABLES: dict[str, str] = {
    "gold_cell_daily": "cell_daily",
    "gold_province_daily": "province_daily",
    "gold_burn_scar_monthly": "burn_scar_monthly",
}


def _active_snapshots(iceberg_root: Path) -> dict[str, int]:
    current = iceberg_root / "current.json"
    if not current.is_file():
        raise FileNotFoundError(
            f"Pointer Iceberg tidak ditemukan: {current}. "
            "Jalankan `gold-publish --strict` dulu."
        )
    payload = json.loads(current.read_text(encoding="utf-8"))
    snapshots = payload.get("snapshots", {})
    missing = [name for name in MART_TABLES.values() if name not in snapshots]
    if missing:
        raise ValueError(
            "current.json belum memuat snapshot untuk: " + ", ".join(missing)
        )
    return {name: int(snapshot) for name, snapshot in snapshots.items()}


def sync_marts(
    iceberg_root: Path,
    dsn: str,
    schema: str = "public",
) -> dict[str, int]:
    """Tulis ulang tabel mart di Postgres dari snapshot Iceberg aktif."""
    snapshots = _active_snapshots(iceberg_root)
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL postgres")
        connection.execute("LOAD postgres")
        escaped = dsn.replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS pg (TYPE postgres)")
        connection.execute(
            f"CREATE SCHEMA IF NOT EXISTS pg.{schema}"
        ).fetchall()

        counts: dict[str, int] = {}
        for target, source in MART_TABLES.items():
            table = catalog.load_table(f"{NAMESPACE}.{source}")
            arrow = table.scan(snapshot_id=snapshots[source]).to_arrow()
            view = f"source_{source}"
            connection.register(view, arrow)
            try:
                connection.execute(
                    f"CREATE OR REPLACE TABLE pg.{schema}.{target} AS "
                    f"SELECT * FROM {view}"
                ).fetchall()
                rows = connection.execute(
                    f"SELECT count(*) FROM pg.{schema}.{target}"
                ).fetchall()
                counts[target] = int(rows[0][0]) if rows else 0
            finally:
                connection.unregister(view)
        connection.execute("DETACH pg")
        return counts
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Salin mart Gold dari Iceberg ke Postgres"
    )
    parser.add_argument(
        "--iceberg-root",
        default=str(ICEBERG_ROOT),
        help="akar katalog + warehouse Iceberg",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_DSN"),
        help="connection string libpq untuk Postgres",
    )
    parser.add_argument("--schema", default="public")
    args = parser.parse_args(argv)

    if not args.dsn:
        parser.error("--dsn atau DATABASE_DSN wajib diisi")

    counts = sync_marts(Path(args.iceberg_root), args.dsn, args.schema)
    print(json.dumps({"schema": args.schema, "tables": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
