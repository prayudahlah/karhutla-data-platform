from __future__ import annotations

import os
import uuid
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from batch.gold.publish import load_catalog, publish_all
from serving.main import create_app
from serving.settings import Settings
from serving.sync_marts import sync_marts

pytestmark = pytest.mark.integration


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_DSN")
    if not dsn:
        pytest.skip("DATABASE_DSN tidak diisi; tes Postgres dilewati")
    return dsn


def _write_parquet(
    connection: duckdb.DuckDBPyConnection,
    folder: Path,
    query: str,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"copy ({query}) to '{(folder / 'part.parquet').as_posix()}' "
        "(format parquet)"
    )


@pytest.fixture()
def gold_root(tmp_path: Path) -> Path:
    root = tmp_path / "gold"
    connection = duckdb.connect()
    try:
        for day, count in (("2026-09-01", 10), ("2026-09-02", 4)):
            _write_parquet(
                connection,
                root / "province_daily" / f"date={day}",
                f"""
                select 'Aceh' as province, 'Sumatera' as island,
                       {count} as hotspot_count, 2 as hotspot_kuat,
                       1 as hotspot_sedang, 0 as hotspot_lemah,
                       0 as hotspot_kandidat, 2 as active_cells,
                       cast(12.5 as decimal(18,3)) as frp_sum,
                       cast(8.0 as decimal(18,3)) as frp_max,
                       timestamp '2026-09-02 01:00:00' as freshness_at,
                       5 as scar_pixels_cum,
                       cast(32.0 as decimal(18,3)) as temp_max,
                       cast(80.0 as decimal(18,3)) as rh_min,
                       cast(2.0 as decimal(18,3)) as precip_sum,
                       cast(3.0 as decimal(18,3)) as wind_speed_max,
                       cast(1.0 as decimal(18,3)) as vpd_max,
                       24 as weather_hours, true as weather_complete,
                       cast(10.0 as decimal(18,3)) as pm25_mean,
                       cast(20.0 as decimal(18,3)) as pm25_max
                """,
            )
        _write_parquet(
            connection,
            root / "cell_daily" / "date=2026-09-01",
            """
            select '0044_0033' as cell_id, 3.125 as cell_lat,
                   103.375 as cell_lon, 'Aceh' as province,
                   'Sumatera' as island, 6 as hotspot_count,
                   1 as label_risk
            """,
        )
        _write_parquet(
            connection,
            root / "burn_scar_monthly" / "burn_month=2026-09",
            """
            select 'Aceh' as province, 'Sumatera' as island,
                   7 as scar_pixels, cast(1.5022 as decimal(18,4)) as scar_area_km2
            """,
        )
    finally:
        connection.close()
    return root


def test_api_reads_postgres_from_iceberg(
    gold_root: Path,
    tmp_path: Path,
) -> None:
    dsn = _dsn()
    schema = f"serving_test_{uuid.uuid4().hex[:8]}"
    iceberg_root = tmp_path / "iceberg"

    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(
            catalog,
            connection,
            gold_root,
            strict=True,
            iceberg_root=iceberg_root,
            run_id="serving-test",
        )
    finally:
        connection.close()

    counts = sync_marts(iceberg_root, dsn, schema)
    assert counts == {
        "gold_cell_daily": 1,
        "gold_province_daily": 2,
        "gold_burn_scar_monthly": 1,
    }

    app = create_app(
        Settings(
            gold_root=gold_root,
            iceberg_root=iceberg_root,
            database_dsn=dsn,
            database_schema=schema,
        )
    )
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["row_counts"] == {
        "province_daily": 2,
        "burn_scar_monthly": 1,
        "cell_daily": 1,
    }
    assert health.json()["iceberg"]["status"] == "ok"

    summary = client.get("/hotspots/summary")
    assert summary.status_code == 200
    assert summary.json()["rows"][0]["hotspot_count"] == 14

    cleanup = duckdb.connect()
    try:
        cleanup.execute("INSTALL postgres")
        cleanup.execute("LOAD postgres")
        escaped = dsn.replace("'", "''")
        cleanup.execute(f"ATTACH '{escaped}' AS pg (TYPE postgres)")
        cleanup.execute(f"DROP SCHEMA IF EXISTS pg.{schema} CASCADE").fetchall()
    finally:
        cleanup.close()
