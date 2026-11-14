from __future__ import annotations

from io import BytesIO
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from batch.silver.parquet import (
    parquet_bytes,
    read_parquet,
    read_parquet_bytes,
    read_parquet_from_store,
    require_columns,
    table_from_rows,
    upload_parquet,
    write_parquet,
)


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        if key in self.objects and not overwrite:
            raise FileExistsError(key)
        self.objects[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return key

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]["body"]


def _sample_table() -> pa.Table:
    return table_from_rows(
        [
            {"sample_id": 1, "label": "alpha"},
            {"sample_id": 2, "label": "beta"},
        ]
    )


def test_table_from_rows_rejects_empty_without_schema() -> None:
    with pytest.raises(ValueError, match="zero rows"):
        table_from_rows([])


def test_table_from_rows_accepts_empty_with_schema() -> None:
    schema = pa.schema([("sample_id", pa.int64()), ("label", pa.string())])
    table = table_from_rows([], schema=schema)
    assert table.num_rows == 0
    assert table.schema == schema


def test_parquet_bytes_uses_zstd_and_roundtrips() -> None:
    body = parquet_bytes(_sample_table())
    parquet_file = pq.ParquetFile(BytesIO(body))
    assert parquet_file.metadata.row_group(0).column(0).compression == "ZSTD"

    table = read_parquet_bytes(body)
    assert table.to_pylist() == [
        {"sample_id": 1, "label": "alpha"},
        {"sample_id": 2, "label": "beta"},
    ]


def test_write_and_read_parquet(tmp_path: Any) -> None:
    path = write_parquet(tmp_path / "nested" / "sample.parquet", _sample_table())
    assert path.exists()
    assert read_parquet(path).num_rows == 2


def test_upload_and_read_from_store() -> None:
    store = FakeStore()
    key = upload_parquet(store, "silver/sample.parquet", _sample_table())
    stored = store.objects[key]

    assert stored["content_type"] == "application/vnd.apache.parquet"
    assert stored["metadata"]["kind"] == "silver-parquet"
    assert read_parquet_from_store(store, key).num_rows == 2


def test_upload_parquet_respects_overwrite() -> None:
    store = FakeStore()
    upload_parquet(store, "silver/sample.parquet", _sample_table())

    with pytest.raises(FileExistsError):
        upload_parquet(store, "silver/sample.parquet", _sample_table())

    upload_parquet(store, "silver/sample.parquet", _sample_table(), overwrite=True)


def test_require_columns() -> None:
    require_columns(_sample_table(), ["sample_id", "label"])

    with pytest.raises(ValueError, match="Missing required Parquet columns: missing"):
        require_columns(_sample_table(), ["sample_id", "missing"])
