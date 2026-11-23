"""Grid 0,25 derajat yang sama dengan ``dbt/macros/grid_cell.sql``.

Dipakai oleh pipeline label Silver dan Gold ML supaya ``cell_id`` konsisten
dengan tabel Gold `cell_daily` milik layer serving. Jangan mengubah konstanta
di sini tanpa mengubah makro dbt.
"""

from __future__ import annotations

import numpy as np

GRID_DEG = 0.25
GRID_LAT_MIN = -11.0
GRID_LON_MIN = 95.0


def grid_cell_id(latitude: float | int, longitude: float | int) -> str:
    """ID satu titik dalam format ``rrrr_cccc``."""
    row = int(np.floor((float(latitude) - GRID_LAT_MIN) / GRID_DEG))
    col = int(np.floor((float(longitude) - GRID_LON_MIN) / GRID_DEG))
    return f"{row:04d}_{col:04d}"


def grid_indices(latitude, longitude) -> tuple[np.ndarray, np.ndarray]:
    """Indeks baris/kolom grid untuk array lintang dan bujur."""
    lat = np.asarray(latitude, dtype="float64")
    lon = np.asarray(longitude, dtype="float64")
    if lat.shape != lon.shape:
        raise ValueError("latitude dan longitude harus sama panjang")
    rows = np.floor((lat - GRID_LAT_MIN) / GRID_DEG).astype("int64")
    cols = np.floor((lon - GRID_LON_MIN) / GRID_DEG).astype("int64")
    return rows, cols


def grid_cell_ids(rows, cols) -> np.ndarray:
    """Array ID ``rrrr_cccc`` dari indeks baris dan kolom."""
    row_values = np.asarray(rows, dtype="int64")
    col_values = np.asarray(cols, dtype="int64")
    if row_values.shape != col_values.shape:
        raise ValueError("row dan col harus sama panjang")
    return np.array(
        [f"{int(row):04d}_{int(col):04d}" for row, col in zip(row_values, col_values, strict=True)],
        dtype=object,
    )


def grid_center_lat(row) -> np.ndarray:
    """Lintang pusat sel dari indeks baris."""
    values = np.asarray(row, dtype="float64")
    return np.round(GRID_LAT_MIN + (values + 0.5) * GRID_DEG, 6)


def grid_center_lon(col) -> np.ndarray:
    """Bujur pusat sel dari indeks kolom."""
    values = np.asarray(col, dtype="float64")
    return np.round(GRID_LON_MIN + (values + 0.5) * GRID_DEG, 6)
