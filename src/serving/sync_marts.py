"""Salin tiga mart Gold Parquet ke Postgres.

Dipakai Metabase dan (nanti) serving yang membaca Postgres. DuckDB membaca
Parquet lalu menulis lewat extension ``postgres``, jadi tidak perlu pandas.

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

GOLD_ROOT = Path(os.environ.get("GOLD_PUBLISH_ROOT", "data/gold/published"))

# Nama tabel di Postgres -> nama tabel Gold.
MART_TABLES: dict[str, str] = {
    "gold_cell_daily": "cell_daily",
    "gold_province_daily": "province_daily",
    "gold_burn_scar_monthly": "burn_scar_monthly",
}


def sync_marts(
    gold_root: Path,
    dsn: str,
    schema: str = "public",
) -> dict[str, int]:
    """Tulis ulang tabel mart di Postgres, kembalikan jumlah barisnya."""
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL postgres")
        connection.execute("LOAD postgres")
        escaped = dsn.replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS pg (TYPE postgres)")

        counts: dict[str, int] = {}
        for target, source in MART_TABLES.items():
            folder = gold_root / source
            if not folder.is_dir() or not any(folder.rglob("*.parquet")):
                raise FileNotFoundError(
                    f"Parquet Gold untuk {source} belum ada di {folder}"
                )
            glob = (folder / "**" / "*.parquet").as_posix()
            connection.execute(
                f"CREATE OR REPLACE TABLE pg.{schema}.{target} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning = true)"
            )
            row = connection.execute(
                f"SELECT count(*) FROM pg.{schema}.{target}"
            ).fetchone()
            counts[target] = int(row[0]) if row else 0
        connection.execute("DETACH pg")
        return counts
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Salin mart Gold ke Postgres")
    parser.add_argument(
        "--gold-root",
        default=str(GOLD_ROOT),
        help="akar Parquet Gold",
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

    counts = sync_marts(Path(args.gold_root), args.dsn, args.schema)
    print(json.dumps({"schema": args.schema, "tables": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
