"""Publish tabel Gold Parquet ke Iceberg v2.

dbt-duckdb menulis Parquet; langkah ini menyalinnya ke tabel Iceberg supaya
F-07 punya snapshot, upsert, dan schema evolution yang bisa ditunjukkan.

Katalog default: SQLite di ``data/gold/_iceberg/catalog.db``.
Warehouse default: ``data/gold/_iceberg/warehouse`` (lokal). Untuk Garage,
set ``ICEBERG_WAREHOUSE=s3://lakehouse/gold/iceberg`` dan kredensial S3.

Contoh::

    python -m batch.gold.publish --table all --mode full
    python -m batch.gold.publish --table province_daily --mode upsert --date 2026-09-20
    python -m batch.gold.publish --verify
    python -m batch.gold.publish --schema-evolution-demo
    python -m batch.gold.publish --backup data/gold/_iceberg_backup
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.expressions import EqualTo
from pyiceberg.types import (
    BooleanType,
    DateType,
    DecimalType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    TimestampType,
)

TABLES: dict[str, str] = {
    "cell_daily": "date",
    "province_daily": "date",
    "burn_scar_monthly": "burn_month",
}

DEFAULT_GOLD_ROOT = Path(
    os.environ.get("GOLD_PUBLISH_ROOT", "data/gold/published")
)
DEFAULT_ICEBERG_ROOT = Path(
    os.environ.get("ICEBERG_ROOT", "data/gold/_iceberg")
)
SNAPSHOT_RETENTION_MS = str(30 * 24 * 60 * 60 * 1000)
NAMESPACE = os.environ.get("ICEBERG_NAMESPACE", "gold")


def catalog_settings(iceberg_root: Path) -> dict[str, Any]:
    """Konfigurasi katalog SQLite dan warehouse."""
    catalog_uri = os.environ.get("ICEBERG_CATALOG_URI") or (
        f"sqlite:///{(iceberg_root / 'catalog.db').resolve().as_posix()}"
    )
    warehouse = os.environ.get("ICEBERG_WAREHOUSE") or (
        iceberg_root / "warehouse"
    ).resolve().as_posix()
    settings: dict[str, Any] = {
        "uri": catalog_uri,
        "warehouse": warehouse,
    }
    if warehouse.startswith("s3://"):
        settings.update(
            {
                "s3.endpoint": os.environ.get(
                    "GARAGE_S3_ENDPOINT", "http://localhost:3900"
                ),
                "s3.access-key-id": os.environ.get("GARAGE_ACCESS_KEY", ""),
                "s3.secret-access-key": os.environ.get(
                    "GARAGE_SECRET_KEY", ""
                ),
                "s3.region": os.environ.get("GARAGE_REGION", "garage"),
                "s3.path-style-access": "true",
            }
        )
    return settings


def load_catalog(iceberg_root: Path) -> Catalog:
    """Muat katalog Iceberg dan pastikan namespace ada."""
    iceberg_root.mkdir(parents=True, exist_ok=True)
    catalog = SqlCatalog("karhutla", **catalog_settings(iceberg_root))
    catalog.create_namespace_if_not_exists(NAMESPACE)
    return catalog


def _iceberg_type(pa_type: pa.DataType) -> Any:
    """Petakan tipe Arrow ke tipe Iceberg untuk kolom baru."""
    if pa.types.is_string(pa_type) or pa.types.is_large_string(pa_type):
        return StringType()
    if pa.types.is_boolean(pa_type):
        return BooleanType()
    if pa.types.is_int32(pa_type):
        return IntegerType()
    if pa.types.is_int64(pa_type):
        return LongType()
    if pa.types.is_float32(pa_type) or pa.types.is_float64(pa_type):
        return DoubleType()
    if pa.types.is_date32(pa_type):
        return DateType()
    if pa.types.is_timestamp(pa_type):
        return TimestampType()
    if pa.types.is_decimal(pa_type):
        return DecimalType(pa_type.precision, pa_type.scale)
    raise TypeError(f"Tipe Arrow belum dipetakan ke Iceberg: {pa_type}")


def read_gold_table(
    connection: duckdb.DuckDBPyConnection,
    gold_root: Path,
    table_name: str,
) -> pa.Table:
    """Baca satu tabel Gold Parquet dengan kolom partisi dari nama folder."""
    folder = gold_root / table_name
    if not folder.is_dir() or not any(folder.rglob("*.parquet")):
        raise FileNotFoundError(
            f"Parquet Gold untuk {table_name} belum ada di {folder}"
        )
    glob = (folder / "**" / "*.parquet").as_posix()
    return connection.sql(
        f"SELECT * FROM read_parquet('{glob}', hive_partitioning = true)"
    ).to_arrow_table()


def _ensure_table(
    catalog: Catalog,
    identifier: str,
    source: pa.Table,
    partition_column: str,
) -> Any:
    """Buat tabel Iceberg bila belum ada, lengkap dengan partisi dan retensi."""
    if not catalog.table_exists(identifier):
        table = catalog.create_table(identifier, schema=source.schema)
        with table.update_spec() as update:
            update.add_identity(partition_column)
    else:
        table = catalog.load_table(identifier)
    with table.transaction() as transaction:
        transaction.set_properties(
            {"history.expire.max-snapshot-age-ms": SNAPSHOT_RETENTION_MS}
        )
    return table


def _add_missing_columns(table: Any, source: pa.Table) -> Any:
    """Tambahkan kolom baru di Parquet ke schema Iceberg (schema evolution)."""
    existing = {field.name for field in table.schema().fields}
    added = False
    for field in source.schema:
        if field.name in existing:
            continue
        with table.update_schema() as update:
            update.add_column(field.name, _iceberg_type(field.type))
        added = True
    if added:
        table = table.catalog.load_table(table.name())
    return table


def _align(table: Any, source: pa.Table) -> pa.Table:
    """Selaraskan urutan/tipe kolom dengan schema Iceberg."""
    target = table.schema().as_arrow()
    arrays: list[pa.Array] = []
    for field in target:
        if field.name in source.column_names:
            arrays.append(source.column(field.name).cast(field.type))
        else:
            arrays.append(pa.nulls(len(source), field.type))
    return pa.Table.from_arrays(arrays, schema=target)


def _filter_partition(
    source: pa.Table,
    partition_column: str,
    value: Any,
) -> pa.Table:
    field = source.schema.field(partition_column)
    mask = pc.equal(source.column(partition_column), pa.scalar(value, field.type))
    return source.filter(mask)


def publish_table(
    catalog: Catalog,
    connection: duckdb.DuckDBPyConnection,
    gold_root: Path,
    table_name: str,
    mode: str = "full",
    partition_value: Any | None = None,
) -> dict[str, Any]:
    """Publish satu tabel Gold ke Iceberg."""
    partition_column = TABLES[table_name]
    source = read_gold_table(connection, gold_root, table_name)
    identifier = f"{NAMESPACE}.{table_name}"
    table = _ensure_table(catalog, identifier, source, partition_column)
    table = _add_missing_columns(table, source)

    if mode == "upsert":
        if partition_value is None:
            raise ValueError("Mode upsert butuh --date atau --month")
        source = _filter_partition(source, partition_column, partition_value)
        table.overwrite(
            _align(table, source),
            overwrite_filter=EqualTo(partition_column, partition_value),
        )
    elif mode == "append":
        table.append(_align(table, source))
    else:
        aligned = _align(table, source)
        if len(table.metadata.snapshots) == 0:
            table.append(aligned)
        else:
            table.overwrite(aligned)

    return _summary(table)


def publish_all(
    catalog: Catalog,
    connection: duckdb.DuckDBPyConnection,
    gold_root: Path,
    mode: str = "full",
    tables: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    selected = tables or tuple(TABLES)
    if mode == "upsert" and len(selected) != 1:
        raise ValueError("Mode upsert hanya untuk satu tabel")
    return [
        publish_table(catalog, connection, gold_root, table_name, mode)
        for table_name in selected
    ]


def _summary(table: Any) -> dict[str, Any]:
    snapshots = []
    for snapshot in table.metadata.snapshots:
        operation = snapshot.summary.operation if snapshot.summary else None
        snapshots.append(
            {
                "snapshot_id": snapshot.snapshot_id,
                "sequence_number": snapshot.sequence_number,
                "timestamp_ms": snapshot.timestamp_ms,
                "operation": getattr(operation, "value", str(operation))
                if operation
                else None,
            }
        )
    name = table.name()
    identifier = ".".join(name) if isinstance(name, tuple) else str(name)
    return {
        "table": identifier,
        "rows": table.scan().to_arrow().num_rows,
        "columns": [field.name for field in table.schema().fields],
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }


def verify_all(
    catalog: Catalog,
    tables: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    selected = tables or tuple(TABLES)
    summaries: list[dict[str, Any]] = []
    for table_name in selected:
        identifier = f"{NAMESPACE}.{table_name}"
        if not catalog.table_exists(identifier):
            summaries.append(
                {"table": identifier, "exists": False, "rows": 0, "snapshot_count": 0}
            )
            continue
        summary = _summary(catalog.load_table(identifier))
        summary["exists"] = True
        summaries.append(summary)
    return summaries


def schema_evolution_demo(catalog: Catalog) -> dict[str, Any]:
    """Buat tabel demo, tambah kolom, dan tunjukkan sebelum/sesudah."""
    identifier = f"{NAMESPACE}.schema_evolution_demo"
    if catalog.table_exists(identifier):
        catalog.drop_table(identifier)
    source = pa.table(
        {
            "id": pa.array([1, 2], type=pa.int64()),
            "label": pa.array(["a", "b"]),
        }
    )
    table = catalog.create_table(identifier, schema=source.schema)
    table.append(source.cast(table.schema().as_arrow()))
    before = [field.name for field in table.schema().fields]
    with table.update_schema() as update:
        update.add_column("note", StringType())
    after = [field.name for field in table.schema().fields]
    extra = pa.table(
        {
            "id": pa.array([3], type=pa.int64()),
            "label": pa.array(["c"]),
            "note": pa.array(["kolom baru"]),
        }
    )
    table.append(_align(table, extra))
    return {
        "table": identifier,
        "columns_before": before,
        "columns_after": after,
        "snapshot_count": len(table.metadata.snapshots),
    }


def backup_iceberg(iceberg_root: Path, destination: Path) -> dict[str, Any]:
    """Salin katalog SQLite dan warehouse ke folder backup."""
    destination.mkdir(parents=True, exist_ok=True)
    catalog_db = iceberg_root / "catalog.db"
    if catalog_db.exists():
        source = sqlite3.connect(catalog_db)
        target = sqlite3.connect(destination / "catalog.db")
        try:
            with target:
                source.backup(target)
        finally:
            source.close()
            target.close()
    warehouse = iceberg_root / "warehouse"
    if warehouse.exists():
        shutil.copytree(warehouse, destination / "warehouse", dirs_exist_ok=True)
    return {
        "source": str(iceberg_root),
        "destination": str(destination),
        "catalog": (destination / "catalog.db").exists(),
        "warehouse": (destination / "warehouse").exists(),
    }


def restore_iceberg(iceberg_root: Path, source: Path) -> dict[str, Any]:
    """Kembalikan katalog dan warehouse dari folder backup."""
    iceberg_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "catalog.db", iceberg_root / "catalog.db")
    shutil.copytree(
        source / "warehouse", iceberg_root / "warehouse", dirs_exist_ok=True
    )
    return {
        "source": str(source),
        "destination": str(iceberg_root),
        "catalog": (iceberg_root / "catalog.db").exists(),
        "warehouse": (iceberg_root / "warehouse").exists(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish Gold Parquet ke Iceberg")
    parser.add_argument(
        "--table",
        choices=["all", *TABLES],
        default="all",
        help="tabel yang dipublish (default: all)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "append", "upsert"],
        default="full",
        help="mode publish (default: full)",
    )
    parser.add_argument("--date", help="tanggal untuk mode upsert (YYYY-MM-DD)")
    parser.add_argument("--month", help="bulan untuk mode upsert (YYYY-MM)")
    parser.add_argument(
        "--gold-root",
        default=str(DEFAULT_GOLD_ROOT),
        help="akar Parquet Gold",
    )
    parser.add_argument(
        "--iceberg-root",
        default=str(DEFAULT_ICEBERG_ROOT),
        help="akar katalog + warehouse Iceberg lokal",
    )
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--schema-evolution-demo", action="store_true")
    parser.add_argument("--backup", help="salin katalog + warehouse ke folder ini")
    parser.add_argument("--restore", help="kembalikan katalog + warehouse dari folder ini")
    args = parser.parse_args(argv)

    iceberg_root = Path(args.iceberg_root)
    if args.backup:
        print(json.dumps(backup_iceberg(iceberg_root, Path(args.backup)), indent=2))
        return 0
    if args.restore:
        print(json.dumps(restore_iceberg(iceberg_root, Path(args.restore)), indent=2))
        return 0

    catalog = load_catalog(iceberg_root)
    if args.schema_evolution_demo:
        print(json.dumps(schema_evolution_demo(catalog), indent=2))
        return 0
    if args.verify:
        print(json.dumps(verify_all(catalog), indent=2))
        return 0

    tables = tuple(TABLES) if args.table == "all" else (args.table,)
    partition_value: Any | None = None
    if args.mode == "upsert":
        if args.table == "burn_scar_monthly":
            if not args.month:
                parser.error("--month wajib untuk upsert burn_scar_monthly")
            partition_value = args.month
        else:
            if not args.date:
                parser.error("--date wajib untuk upsert tabel harian")
            partition_value = date.fromisoformat(args.date)

    connection = duckdb.connect()
    try:
        summaries = publish_all(
            catalog,
            connection,
            Path(args.gold_root),
            args.mode,
            tables,
        ) if not (args.mode == "upsert") else [
            publish_table(
                catalog,
                connection,
                Path(args.gold_root),
                tables[0],
                args.mode,
                partition_value,
            )
        ]
    finally:
        connection.close()
    print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
