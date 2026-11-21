from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from serving.main import create_app
from serving.settings import Settings


@pytest.fixture()
def gold_root(tmp_path: Path) -> Path:
    con = duckdb.connect()

    con.execute(
        """
        create table province_daily as
        select * from (values
            ('Aceh', date '2026-09-01', 10, 2, 1, 0, 3, 2,
             12.5, 1.25, 8.0, timestamp '2026-09-02 01:00:00',
             5, 1.073, 32.0, 80.0, 2.0, 3.0, 1.0, 24, true, 10.0, 20.0),
            ('Aceh', date '2026-09-02', 4, 1, 1, 0, 0, 1,
             6.0, 1.5, 4.0, timestamp '2026-09-02 01:00:00',
             7, 1.5022, 31.0, 78.0, 0.0, 2.0, 0.8, 24, true, 12.0, 25.0),
            ('Bali', date '2026-09-01', 2, 0, 1, 0, 0, 1,
             3.0, 1.5, 3.0, timestamp '2026-09-02 02:00:00',
             1, 0.2146, 30.0, 82.0, 0.0, 4.0, 0.9, 22, true, 8.0, 15.0)
        ) as t(
            province, date, hotspot_count, hotspot_kuat, hotspot_sedang,
            hotspot_lemah, hotspot_kandidat, active_cells,
            frp_sum, frp_mean, frp_max, freshness_at,
            scar_pixels_cum, scar_area_km2_cum,
            temp_max, rh_min, precip_sum, wind_speed_max, vpd_max,
            weather_hours, weather_complete, pm25_mean, pm25_max
        )
        """
    )
    con.execute(
        """
        create table burn_scar_monthly as
        select * from (values
            ('2026-09', 'Aceh', 7, 1.5022, 1, 3.2, 0.8,
             date '2026-09-01', date '2026-09-02'),
            ('2026-09', 'Bali', 1, 0.2146, 1, 3.0, 0.5,
             date '2026-09-01', date '2026-09-01')
        ) as t(
            burn_month, province, scar_pixels, scar_area_km2, tile_count,
            qa_mean, uncertainty_mean, first_burn_date, last_burn_date
        )
        """
    )
    con.execute(
        """
        create table cell_daily as
        select * from (values
            ('0044_0033', date '2026-09-01', 3.125, 103.375, 'Aceh',
             6, 1, 1, 0, 0, 12.5, 1.073, true),
            ('0044_0034', date '2026-09-01', 3.375, 103.625, 'Aceh',
             4, 1, 0, 0, 0, 6.0, 0.0, true)
        ) as t(
            cell_id, date, cell_lat, cell_lon, province,
            hotspot_count, hotspot_kuat, hotspot_sedang, hotspot_lemah,
            hotspot_kandidat, frp_sum, scar_area_km2_cum, weather_complete
        )
        """
    )

    for table in ("province_daily", "burn_scar_monthly", "cell_daily"):
        folder = tmp_path / table / (
            "burn_month=2026-09" if table == "burn_scar_monthly" else "date=2026-09-01"
        )
        folder.mkdir(parents=True)
        con.execute(
            f"copy {table} to '{(folder / 'part.parquet').as_posix()}' "
            "(format parquet)"
        )
    con.close()
    return tmp_path


@pytest.fixture()
def client(gold_root: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                gold_root=gold_root,
                iceberg_root=gold_root / "iceberg",
            )
        )
    )


def test_health_reports_rows(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["row_counts"] == {
        "province_daily": 3,
        "burn_scar_monthly": 2,
        "cell_daily": 2,
    }
    assert payload["province_count"] == 2


def test_meta_provinces(client: TestClient) -> None:
    response = client.get("/meta/provinces")

    assert response.status_code == 200
    assert response.json()["provinces"] == ["Aceh", "Bali"]


def test_hotspots_daily_filters_province(client: TestClient) -> None:
    response = client.get("/hotspots/daily", params={"province": "Aceh"})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2
    assert {row["province"] for row in rows} == {"Aceh"}


def test_hotspots_summary(client: TestClient) -> None:
    response = client.get("/hotspots/summary")

    assert response.status_code == 200
    rows = {row["province"]: row for row in response.json()["rows"]}
    assert rows["Aceh"]["hotspot_count"] == 14
    assert rows["Aceh"]["hotspot_kuat"] == 3
    assert rows["Bali"]["hotspot_count"] == 2


def test_frp_daily(client: TestClient) -> None:
    response = client.get("/frp/daily", params={"province": "Aceh"})

    assert response.status_code == 200
    assert len(response.json()["rows"]) == 2


def test_burn_scar_monthly(client: TestClient) -> None:
    response = client.get("/burn-scar/monthly", params={"month": "2026-09"})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["scar_pixels"] == 7


def test_burn_scar_cumulative(client: TestClient) -> None:
    response = client.get("/burn-scar/cumulative", params={"province": "Aceh"})

    assert response.status_code == 200
    assert response.json()["rows"][-1]["scar_pixels_cum"] == 7


def test_weather_and_air_quality(client: TestClient) -> None:
    weather = client.get("/weather/daily", params={"province": "Aceh"})
    air = client.get("/air-quality/daily", params={"province": "Aceh"})

    assert weather.status_code == 200
    assert air.status_code == 200
    assert weather.json()["rows"][0]["weather_complete"] is True
    assert air.json()["rows"][0]["pm25_mean"] == 10.0


def test_cells_hotspots_for_date(client: TestClient) -> None:
    response = client.get("/cells/hotspots", params={"date": "2026-09-01"})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["hotspot_count"] == 6


def test_predictions_are_not_available_yet(client: TestClient) -> None:
    response = client.get("/predictions/daily")

    assert response.status_code == 503
    assert "belum tersedia" in response.json()["detail"]


def test_invalid_date_returns_400(client: TestClient) -> None:
    response = client.get("/hotspots/daily", params={"start": "2026-13-01"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Parameter tidak valid"


def test_invalid_limit_returns_400(client: TestClient) -> None:
    response = client.get("/hotspots/daily", params={"limit": 0})

    assert response.status_code == 400


def test_missing_gold_returns_503(tmp_path: Path) -> None:
    app = create_app(Settings(gold_root=tmp_path / "tidak-ada"))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert "belum ada" in response.json()["detail"]


def test_partition_columns_are_read_from_folder_names(tmp_path: Path) -> None:
    """dbt menghapus kolom partisi dari berkas; nilainya ada di nama folder."""
    from serving.db import GoldStore

    layout = {
        "province_daily": ("date=2026-09-01", "select 'Aceh' as province, 1 as hotspot_count"),
        "cell_daily": ("date=2026-09-01", "select 'Aceh' as province"),
        "burn_scar_monthly": (
            "burn_month=2026-09",
            "select 'Aceh' as province, 1 as scar_pixels",
        ),
    }
    con = duckdb.connect()
    for table, (partition, select_sql) in layout.items():
        folder = tmp_path / table / partition
        folder.mkdir(parents=True)
        con.execute(
            f"copy ({select_sql}) to '{(folder / 'part.parquet').as_posix()}' "
            "(format parquet)"
        )
    con.close()

    store = GoldStore(tmp_path)
    date_rows = store.query("select distinct date from province_daily")
    month_rows = store.query("select distinct burn_month from burn_scar_monthly")

    assert [row["date"] for row in date_rows] == [date(2026, 9, 1)]
    assert [row["burn_month"] for row in month_rows] == ["2026-09"]


def test_health_reports_iceberg_state(
    gold_root: Path,
    tmp_path: Path,
) -> None:
    iceberg_root = tmp_path / "ice"
    iceberg_root.mkdir()
    published_at = datetime.now(UTC).isoformat()
    (iceberg_root / "current.json").write_text(
        json.dumps(
            {
                "published_at": published_at,
                "snapshots": {
                    "cell_daily": 1,
                    "province_daily": 2,
                    "burn_scar_monthly": 3,
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            Settings(gold_root=gold_root, iceberg_root=iceberg_root)
        )
    )

    payload = client.get("/health").json()

    assert payload["iceberg"]["status"] == "ok"
    assert payload["iceberg"]["stale"] is False
    assert payload["iceberg"]["snapshots"]["cell_daily"] == 1


def test_health_marks_stale_iceberg(
    gold_root: Path,
    tmp_path: Path,
) -> None:
    iceberg_root = tmp_path / "ice"
    iceberg_root.mkdir()
    (iceberg_root / "current.json").write_text(
        json.dumps(
            {
                "published_at": "2020-01-01T00:00:00+00:00",
                "snapshots": {},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            Settings(gold_root=gold_root, iceberg_root=iceberg_root)
        )
    )

    payload = client.get("/health").json()

    assert payload["iceberg"]["stale"] is True


def test_health_marks_missing_iceberg(gold_root: Path) -> None:
    client = TestClient(
        create_app(
            Settings(gold_root=gold_root, iceberg_root=gold_root / "missing")
        )
    )

    payload = client.get("/health").json()

    assert payload["iceberg"]["status"] == "missing"
    assert payload["iceberg"]["stale"] is True
