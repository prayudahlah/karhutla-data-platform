from __future__ import annotations

import numpy as np
import pytest

from common.grid import (
    GRID_DEG,
    GRID_LAT_MIN,
    GRID_LON_MIN,
    grid_cell_id,
    grid_cell_ids,
    grid_center_lat,
    grid_center_lon,
    grid_indices,
)


def test_grid_cell_id_matches_dbt_contract() -> None:
    # Riau: (0.5071, 101.4478) -> row 46, col 25.
    assert grid_cell_id(0.5071, 101.4478) == "0046_0025"


def test_grid_cell_id_is_zero_padded() -> None:
    assert grid_cell_id(GRID_LAT_MIN, GRID_LON_MIN) == "0000_0000"


def test_grid_indices_vectorized() -> None:
    rows, cols = grid_indices(
        np.array([0.5071, GRID_LAT_MIN]),
        np.array([101.4478, GRID_LON_MIN]),
    )
    assert rows.tolist() == [46, 0]
    assert cols.tolist() == [25, 0]
    assert grid_cell_ids(rows, cols).tolist() == ["0046_0025", "0000_0000"]


def test_grid_centers_are_inside_cells() -> None:
    row = np.array([0, 46])
    col = np.array([0, 25])
    lat = grid_center_lat(row)
    lon = grid_center_lon(col)
    assert lat.tolist() == [GRID_LAT_MIN + GRID_DEG / 2, GRID_LAT_MIN + 46.5 * GRID_DEG]
    assert lon.tolist() == [GRID_LON_MIN + GRID_DEG / 2, GRID_LON_MIN + 25.5 * GRID_DEG]


def test_grid_indices_reject_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        grid_indices([0.0, 1.0], [100.0])
