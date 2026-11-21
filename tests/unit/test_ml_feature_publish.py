from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import pandas as pd  # noqa: E402

from ml.dataset import read_parquet_dataset  # noqa: E402
from ml.feature_publish import (  # noqa: E402
    ALL_FEATURE_COLUMNS,
    CELL_FEATURE_COLUMNS,
    PROVINCE_CONTEXT_COLUMNS,
    FeaturePublishError,
    _write_partitioned,
    build_feature_frames,
)
from ml.features import CONTEXT_COLUMNS, add_province  # noqa: E402
from ml.province import load_provinces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def _provinces():
    return load_provinces(PROVINCES_CSV)


def _context_for(frame: pd.DataFrame):
    provinces = _provinces()
    with_province = add_province(
        frame,
        provinces,
        lat_column="center_lat",
        lon_column="center_lon",
    )
    rows = []
    for day, date in enumerate(sorted(frame["date"].unique())):
        for province in sorted(with_province["province"].dropna().unique()):
            row = {"province": province, "date": date}
            for index, column in enumerate(CONTEXT_COLUMNS):
                row[column] = float(day * 10 + index + 1)
            rows.append(row)
    return pd.DataFrame(rows)


def test_build_feature_frames_has_39_features_and_no_label(cell_factory) -> None:
    frame = cell_factory(days=4, cells=2)
    tables = build_feature_frames(
        frame,
        _context_for(frame),
        provinces=_provinces(),
        require_context=True,
    )

    assert len(tables.cells) == len(frame)
    assert set(CELL_FEATURE_COLUMNS) <= set(tables.cells.columns)
    assert set(PROVINCE_CONTEXT_COLUMNS) <= set(tables.provinces.columns)
    assert "label" in tables.cells.columns
    assert "label" not in tables.manifest["feature_columns"]
    assert tables.manifest["feature_columns"] == list(ALL_FEATURE_COLUMNS)
    assert len(tables.manifest["feature_columns"]) == 39
    assert tables.cells["event_timestamp"].notna().all()
    assert tables.cells["event_timestamp"].dt.normalize().equals(
        tables.cells["date"].dt.normalize()
    )


def test_build_feature_frames_requires_context_by_default(cell_factory) -> None:
    frame = cell_factory(days=2, cells=1)
    with pytest.raises(FeaturePublishError, match="Konteks"):
        build_feature_frames(frame, None, provinces=_provinces(), require_context=True)


def test_build_feature_frames_can_skip_context(cell_factory) -> None:
    frame = cell_factory(days=2, cells=1)
    tables = build_feature_frames(
        frame,
        None,
        provinces=_provinces(),
        require_context=False,
    )
    assert tables.provinces.empty
    assert len(tables.manifest["feature_columns"]) == len(CELL_FEATURE_COLUMNS) + 1
    assert "temp_max" not in tables.manifest["feature_columns"]


def test_write_partitioned_roundtrip(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=4, cells=2)
    tables = build_feature_frames(
        frame,
        _context_for(frame),
        provinces=_provinces(),
    )
    root = tmp_path / "ml_feature_cell_day"
    _write_partitioned(tables.cells, root)

    loaded = read_parquet_dataset(root)
    assert len(loaded) == len(tables.cells)
    assert set(CELL_FEATURE_COLUMNS) <= set(loaded.columns)
    assert "date" in loaded.columns
    assert loaded["cell_id"].nunique() == 2
