"""Akses read-only ke tabel Gold.

Dua backend:

- **Postgres** (default bila ``DATABASE_DSN`` diisi): DuckDB attach Postgres,
  lalu view ``province_daily``/``burn_scar_monthly``/``cell_daily`` dibaca dari
  tabel ``gold_*``. Ini jalur serving sesuai ADR-002.
- **Parquet** (fallback lokal/tes): DuckDB membaca Gold Parquet langsung.

Postgres diisi oleh ``sync_marts.py`` dari snapshot Iceberg aktif.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _json_scalar(value: Any) -> Any:
    """Ubah Decimal menjadi float supaya JSON memuat angka, bukan string.

    Pydantic v2 menyerialkan Decimal sebagai string. API ini lebih nyaman
    dipakai dashboard kalau nilainya angka.
    """
    return float(value) if isinstance(value, Decimal) else value


class GoldUnavailable(RuntimeError):
    """Dilempar bila Parquet/Postgres Gold belum siap."""


class GoldStore:
    """Koneksi DuckDB dengan satu view per tabel Gold."""

    def __init__(
        self,
        root: Path,
        dsn: str | None = None,
        schema: str = "public",
    ) -> None:
        self.root = root
        self.dsn = dsn or None
        self.schema = schema
        self._con: duckdb.DuckDBPyConnection | None = None
        # FastAPI menjalankan endpoint sync di threadpool. Satu koneksi DuckDB
        # tidak boleh dipakai bersamaan, jadi query diserialkan.
        self._lock = threading.Lock()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = self._connect()
        return self._con

    def _connect(self) -> duckdb.DuckDBPyConnection:
        if self.dsn:
            return self._connect_postgres()
        return self._connect_parquet()

    def _connect_postgres(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        try:
            con.execute("INSTALL postgres")
            con.execute("LOAD postgres")
            escaped = self.dsn.replace("'", "''")  # type: ignore[union-attr]
            con.execute(f"ATTACH '{escaped}' AS pg (TYPE postgres)")
            for table, remote in (
                ("province_daily", "gold_province_daily"),
                ("burn_scar_monthly", "gold_burn_scar_monthly"),
                ("cell_daily", "gold_cell_daily"),
            ):
                con.execute(
                    f"CREATE OR REPLACE VIEW {table} AS "
                    f"SELECT * FROM pg.{self.schema}.{remote}"
                )
        except Exception as exc:  # noqa: BLE001 - diteruskan sebagai 503
            con.close()
            raise GoldUnavailable(f"Gagal membaca Postgres: {exc}") from exc
        return con

    def _connect_parquet(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        for table in ("province_daily", "burn_scar_monthly", "cell_daily"):
            folder = self.root / table
            if not folder.is_dir() or not any(folder.rglob("*.parquet")):
                raise GoldUnavailable(
                    f"Parquet Gold untuk {table} belum ada di {folder}. "
                    "Jalankan `task gold-build` dulu."
                )
            glob = (folder / "**" / "*.parquet").as_posix()
            # Partition_by di dbt menghapus kolom partisi dari isi berkas, jadi
            # kolom itu harus diambil dari nama folder. Kalau berkas masih
            # menyimpan kolomnya (mis. fixture uji), jangan aktifkan hive agar
            # nilai di dalam berkas tidak tertimpa string folder.
            partition = "burn_month" if table == "burn_scar_monthly" else "date"
            columns = con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{glob}', hive_partitioning = false)"
            ).fetchall()
            has_partition = any(column[0] == partition for column in columns)
            hive = "false" if has_partition else "true"
            con.execute(
                f"CREATE OR REPLACE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning = {hive})"
            )
        return con

    def query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Jalankan SQL dan kembalikan list of dict."""
        with self._lock:
            cursor = self.connection.execute(sql, list(params or []))
            columns = [description[0] for description in cursor.description]
            return [
                {column: _json_scalar(value) for column, value in zip(columns, row, strict=True)}
                for row in cursor.fetchall()
            ]

    def query_one(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None
