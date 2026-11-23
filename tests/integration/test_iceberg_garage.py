from __future__ import annotations

import os
import uuid
from pathlib import Path

import pyarrow as pa
import pytest

from batch.gold.publish import NAMESPACE, load_catalog

pytestmark = pytest.mark.integration


def _require_garage() -> None:
    warehouse = os.environ.get("ICEBERG_WAREHOUSE", "")
    if not warehouse.startswith("s3://"):
        pytest.skip("ICEBERG_WAREHOUSE bukan s3://; Garage test dilewati")
    access_key = os.environ.get("GARAGE_ACCESS_KEY_ID") or os.environ.get(
        "GARAGE_ACCESS_KEY"
    )
    secret_key = os.environ.get("GARAGE_SECRET_ACCESS_KEY") or os.environ.get(
        "GARAGE_SECRET_KEY"
    )
    if not access_key or not secret_key:
        pytest.skip("Kredensial Garage tidak diisi")


def test_iceberg_append_scan_on_garage(tmp_path: Path) -> None:
    _require_garage()
    catalog = load_catalog(tmp_path)
    identifier = f"{NAMESPACE}.garage_test_{uuid.uuid4().hex[:8]}"
    source = pa.table(
        {
            "id": pa.array([1, 2], type=pa.int64()),
            "label": pa.array(["a", "b"]),
        }
    )
    try:
        table = catalog.create_table(identifier, schema=source.schema)
        table.append(source.cast(table.schema().as_arrow()))

        assert table.scan().to_arrow().num_rows == 2
        assert len(table.metadata.snapshots) == 1
    finally:
        if catalog.table_exists(identifier):
            catalog.drop_table(identifier)
