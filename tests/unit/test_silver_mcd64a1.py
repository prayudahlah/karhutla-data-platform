from __future__ import annotations

import io
from datetime import date
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest

from batch.silver.mcd64a1 import (
    Mcd64a1SilverError,
    TileData,
    TileGrid,
    burn_date_from_doy,
    month_doy_range,
    normalize_month,
    parse_month,
    parse_struct_metadata,
    parse_tile,
    pixel_centers,
    read_tile_bytes,
    sinusoidal_to_latlon,
    tile_from_key,
)
from common.config import BurnedAreaSettings

METADATA = """
GROUP=SwathStructure
	OBJECT=GRID
		GridName="h28v09"
		XDim=4
		YDim=3
		UpperLeftPointMtrs=(0.000000,-0.000005)
		LowerRightMtrs=(400.000000,-300.000000)
	END_OBJECT=GRID
END_GROUP=SwathStructure
"""

BBOX = (95.0, -11.0, 141.0, 6.0)


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
        return "sha"

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]["body"]

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


def _grid() -> TileGrid:
    return TileGrid(ulx=0.0, uly=0.0, px=100.0, py=100.0, nx=4, ny=3)


def _tile(month: str = "2026-09", tile: str = "h28v09") -> TileData:
    burn = np.array(
        [
            [0, 252, 0, 0],
            [366, 0, 367, 0],
            [0, 0, 0, 251],
        ],
        dtype=np.int16,
    )
    return TileData(
        tile=tile,
        month=month,
        grid=_grid(),
        burn=burn,
        qa=np.full((3, 4), 3, dtype=np.uint8),
        uncertainty=np.zeros((3, 4), dtype=np.uint8),
        first_day=np.where(burn > 0, 244, 0).astype(np.int16),
        last_day=np.where(burn > 0, 273, 0).astype(np.int16),
    )


def test_parse_month_rejects_wrong_shape() -> None:
    with pytest.raises(Mcd64a1SilverError):
        parse_month("2026-9-1")


def test_month_doy_range_for_september() -> None:
    assert month_doy_range("2026-09") == (244, 273)


def test_month_doy_range_for_leap_february() -> None:
    assert month_doy_range("2024-02") == (32, 60)


def test_burn_date_from_doy_maps_to_calendar() -> None:
    assert burn_date_from_doy("2026-09", 244) == date(2026, 9, 1)
    assert burn_date_from_doy("2026-09", 252) == date(2026, 9, 9)


def test_burn_date_outside_month_raises() -> None:
    with pytest.raises(Mcd64a1SilverError):
        burn_date_from_doy("2026-09", 366)


def test_parse_struct_metadata_computes_pixel_size() -> None:
    grid = parse_struct_metadata(METADATA, nx=4, ny=3)

    assert grid.px == pytest.approx(100.0)
    assert grid.py == pytest.approx(100.0)
    assert grid.x_max == pytest.approx(400.0)
    assert grid.y_min == pytest.approx(-300.0)


def test_parse_struct_metadata_rejects_missing_corner() -> None:
    with pytest.raises(Mcd64a1SilverError):
        parse_struct_metadata("UpperLeftPointMtrs=(0,0)", nx=4, ny=3)


def test_parse_struct_metadata_rejects_zero_pixel() -> None:
    broken = METADATA.replace("(400.000000,-300.000000)", "(0.000000,-300.000000)")

    with pytest.raises(Mcd64a1SilverError):
        parse_struct_metadata(broken, nx=4, ny=3)


def test_pixel_centers_and_latlon_near_equator() -> None:
    rows = np.array([0])
    cols = np.array([1])
    x, y = pixel_centers(_grid(), rows, cols)
    latitude, longitude = sinusoidal_to_latlon(x, y)

    assert latitude[0] == pytest.approx(-0.00045, abs=1e-4)
    assert 0 < longitude[0] < 0.01


def test_tile_from_key_reads_tile_name() -> None:
    key = "bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/a.hdf"

    assert tile_from_key(key) == "h28v09"


def test_tile_from_key_rejects_unexpected_key() -> None:
    with pytest.raises(Mcd64a1SilverError):
        tile_from_key("bronze/mcd64a1/random.hdf")


def test_parse_tile_keeps_only_days_inside_month() -> None:
    result = parse_tile(_tile(), bbox=BBOX, source_file="key", run_id="run")

    # 366 dan 367 berada di luar September: dua baris scar, dua karantina.
    assert len(result.scar_rows) == 2
    assert len(result.rejected_rows) == 2


def test_parse_tile_marks_bbox_membership() -> None:
    rows = parse_tile(_tile(), bbox=BBOX, source_file="key", run_id="run").scar_rows

    # Titik tengah tile contoh berada di sekitar 0 LU, 0 BT: di luar bbox.
    assert all(row["in_bbox"] is False for row in rows)


def test_parse_tile_bbox_true_for_indonesia_point() -> None:
    grid = TileGrid(ulx=13_200_000.0, uly=-300_000.0, px=463.0, py=463.0, nx=4, ny=3)
    tile = TileData(
        tile="h28v09",
        month="2026-09",
        grid=grid,
        burn=np.array([[252, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], dtype=np.int16),
        qa=np.full((3, 4), 3, dtype=np.uint8),
        uncertainty=np.zeros((3, 4), dtype=np.uint8),
        first_day=np.zeros((3, 4), dtype=np.int16),
        last_day=np.zeros((3, 4), dtype=np.int16),
    )

    rows = parse_tile(tile, bbox=BBOX, source_file="key", run_id="run").scar_rows

    assert rows[0]["in_bbox"] is True


def test_parse_tile_records_grid_for_join() -> None:
    result = parse_tile(_tile(), bbox=BBOX, source_file="key", run_id="run")

    assert result.tile_row["tile"] == "h28v09"
    assert result.tile_row["nx"] == 4
    assert result.tile_row["px"] == pytest.approx(100.0)
    assert result.coverage_row["pixels_burned"] == 2
    assert result.coverage_row["pixels_outside_month"] == 2


def test_normalize_month_writes_scar_tiles_coverage_and_dq(monkeypatch) -> None:
    store = FakeStore()
    bronze_key = "bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/a.hdf"
    store.objects[bronze_key] = {"body": b"hdf", "content_type": "", "metadata": {}}

    monkeypatch.setattr(
        "batch.silver.mcd64a1.read_tile_bytes",
        lambda payload, *, tile, month: _tile(month=month, tile=tile),
    )

    summary = normalize_month(
        store,
        BurnedAreaSettings(bronze_prefix="bronze/mcd64a1"),
        month="2026-09",
        run_id="20261114T090000Z-abcdef12",
    )

    assert summary["scar_rows"] == 2
    assert summary["quarantined_rows"] == 2
    # Separuh piksel tile contoh berada di luar September, jadi DQ menandai
    # anomali ini sebagai failed meskipun barisnya tetap ditulis.
    assert summary["dq_status"] == "failed"

    keys = sorted(store.objects)
    assert any("/dataset=burn_scar/date=2026-09-09/" in key for key in keys)
    assert any("/dataset=burn_scar/date=2026-09-08/" in key for key in keys)
    assert any("/dataset=tiles/date=2026-09-01/" in key for key in keys)
    assert any("/dataset=coverage/date=2026-09-01/" in key for key in keys)
    assert any(key.startswith("silver/_dq/mcd64a1/") for key in keys)
    assert any(key.startswith("silver/_quarantine/mcd64a1/") for key in keys)


def test_normalize_month_clean_tile_passes_dq(monkeypatch) -> None:
    store = FakeStore()
    bronze_key = "bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/a.hdf"
    store.objects[bronze_key] = {"body": b"hdf", "content_type": "", "metadata": {}}

    clean = TileData(
        tile="h28v09",
        month="2026-09",
        grid=_grid(),
        burn=np.array([[0, 252, 0, 0], [0, 0, 0, 0], [0, 0, 0, 251]], dtype=np.int16),
        qa=np.full((3, 4), 3, dtype=np.uint8),
        uncertainty=np.zeros((3, 4), dtype=np.uint8),
        first_day=np.zeros((3, 4), dtype=np.int16),
        last_day=np.zeros((3, 4), dtype=np.int16),
    )
    monkeypatch.setattr(
        "batch.silver.mcd64a1.read_tile_bytes",
        lambda payload, *, tile, month: clean,
    )

    summary = normalize_month(
        store,
        BurnedAreaSettings(bronze_prefix="bronze/mcd64a1"),
        month="2026-09",
        run_id="20261114T090000Z-abcdef12",
    )

    assert summary["scar_rows"] == 2
    assert summary["quarantined_rows"] == 0
    assert summary["dq_status"] == "passed"


def test_normalize_month_scar_parquet_has_schema(monkeypatch) -> None:
    store = FakeStore()
    bronze_key = "bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/a.hdf"
    store.objects[bronze_key] = {"body": b"hdf", "content_type": "", "metadata": {}}
    monkeypatch.setattr(
        "batch.silver.mcd64a1.read_tile_bytes",
        lambda payload, *, tile, month: _tile(month=month, tile=tile),
    )

    normalize_month(
        store,
        BurnedAreaSettings(bronze_prefix="bronze/mcd64a1"),
        month="2026-09",
        run_id="20261114T090000Z-abcdef12",
    )

    scar_key = next(
        key
        for key in sorted(store.objects)
        if key.startswith("silver/_normalized/") and "/dataset=burn_scar/" in key
    )
    table = pq.read_table(io.BytesIO(store.objects[scar_key]["body"]))

    assert table.num_rows == 1
    assert "burn_date" in table.column_names
    assert table.schema.field("burn_date").type == __import__("pyarrow").date32()


def test_normalize_month_without_bronze_raises() -> None:
    with pytest.raises(Mcd64a1SilverError):
        normalize_month(
            FakeStore(),
            BurnedAreaSettings(bronze_prefix="bronze/mcd64a1"),
            month="2026-09",
            run_id="run",
        )


def test_read_tile_bytes_cleans_up_temp_file(monkeypatch) -> None:
    created: list[str] = []

    def fake_read(path, *, tile, month):
        created.append(str(path))
        return _tile(month=month, tile=tile)

    monkeypatch.setattr("batch.silver.mcd64a1.read_tile", fake_read)

    read_tile_bytes(b"hdf", tile="h28v09", month="2026-09")

    assert created
    from pathlib import Path

    assert not Path(created[0]).exists()


def test_main_wires_normalize_month(monkeypatch) -> None:
    from batch.silver import mcd64a1 as module

    captured: list[dict[str, Any]] = []

    def fake_normalize(store, settings, *, month, run_id, local_root=None, overwrite=False):
        captured.append({"month": month, "run_id": run_id, "local_root": local_root})
        return {"month": month}

    class DummySettings:
        garage = object()
        burned_area = object()

        @staticmethod
        def from_env():
            return DummySettings()

    monkeypatch.setattr(module, "normalize_month", fake_normalize)
    monkeypatch.setattr(module, "Settings", DummySettings)
    monkeypatch.setattr(module, "BronzeStore", lambda settings: object())

    assert module.main(["normalize", "--month", "2026-09", "--run-id", "r1"]) == 0
    assert captured[0]["month"] == "2026-09"
    assert captured[0]["run_id"] == "r1"
    assert captured[0]["local_root"] is not None


def test_normalize_twice_overwrites_without_failing(monkeypatch) -> None:
    store = FakeStore()
    bronze_key = "bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/a.hdf"
    store.objects[bronze_key] = {"body": b"hdf", "content_type": "", "metadata": {}}
    monkeypatch.setattr(
        "batch.silver.mcd64a1.read_tile_bytes",
        lambda payload, *, tile, month: _tile(month=month, tile=tile),
    )
    settings = BurnedAreaSettings(bronze_prefix="bronze/mcd64a1")

    first = normalize_month(store, settings, month="2026-09", run_id="run-a")
    second = normalize_month(store, settings, month="2026-09", run_id="run-b")

    assert first["scar_rows"] == second["scar_rows"] == 2
    scar_keys = [
        key
        for key in store.objects
        if key.startswith("silver/_normalized/") and "/dataset=burn_scar/" in key
    ]
    assert len(scar_keys) == 2
