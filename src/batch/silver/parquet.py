"""Parquet helpers shared by Silver normalizers and dbt loads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_COMPRESSION = "zstd"
PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


class ObjectStore(Protocol):
    """Minimal storage contract used by Silver writers."""

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str: ...

    def read_bytes(self, key: str) -> bytes: ...


def table_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    schema: pa.Schema | None = None,
) -> pa.Table:
    """Build a table from dictionaries, optionally enforcing a schema."""
    row_list = list(rows)
    if schema is not None:
        return pa.Table.from_pylist(row_list, schema=schema)
    if not row_list:
        raise ValueError("Cannot infer a Parquet schema from zero rows; pass schema=...")
    return pa.Table.from_pylist(row_list)


def parquet_bytes(
    table: pa.Table,
    *,
    compression: str = DEFAULT_COMPRESSION,
) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression=compression)
    return sink.getvalue().to_pybytes()


def write_parquet(
    path: str | Path,
    table: pa.Table,
    *,
    compression: str = DEFAULT_COMPRESSION,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output, compression=compression)
    return output


def read_parquet(path: str | Path) -> pa.Table:
    return pq.read_table(path)


def read_parquet_bytes(data: bytes) -> pa.Table:
    return pq.read_table(BytesIO(data))


def read_parquet_from_store(store: ObjectStore, key: str) -> pa.Table:
    return read_parquet_bytes(store.read_bytes(key))


def upload_parquet(
    store: ObjectStore,
    key: str,
    table: pa.Table,
    *,
    compression: str = DEFAULT_COMPRESSION,
    metadata: dict[str, str] | None = None,
    overwrite: bool = False,
) -> str:
    object_metadata = {"kind": "silver-parquet"}
    if metadata:
        object_metadata.update(metadata)
    return store.put_bytes(
        key,
        parquet_bytes(table, compression=compression),
        content_type=PARQUET_CONTENT_TYPE,
        metadata=object_metadata,
        overwrite=overwrite,
    )


def require_columns(table: pa.Table, columns: Iterable[str]) -> None:
    missing = [name for name in columns if name not in table.column_names]
    if missing:
        raise ValueError(f"Missing required Parquet columns: {', '.join(missing)}")
