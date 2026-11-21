from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.config import MLSettings  # noqa: E402
from ml.dataset import prepare_dataset  # noqa: E402
from ml.feast_dataset import FEATURE_COLUMNS, prepare_from_feast  # noqa: E402
from ml.feature_publish import (  # noqa: E402
    CELL_FEATURE_COLUMNS,
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
    with_province = add_province(
        frame,
        _provinces(),
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


class _FakeJob:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def to_df(self) -> pd.DataFrame:
        return self._frame.copy()


class _FakeStore:
    """FeatureStore palsu: join langsung dari tabel fitur yang sama."""

    def __init__(self, cells: pd.DataFrame, provinces: pd.DataFrame) -> None:
        self.cells = cells
        self.provinces = provinces

    def get_feature_service(self, name: str) -> str:
        return name

    def get_historical_features(self, *, entity_df: pd.DataFrame, features: str):
        cell_columns = ["cell_id", "event_timestamp", *CELL_FEATURE_COLUMNS]
        context_columns = ["province", "event_timestamp", *CONTEXT_COLUMNS]
        merged = entity_df.merge(
            self.cells[cell_columns],
            on=["cell_id", "event_timestamp"],
            how="left",
            validate="many_to_one",
        ).merge(
            self.provinces[context_columns],
            on=["province", "event_timestamp"],
            how="left",
            validate="many_to_one",
        )
        return _FakeJob(merged)


def test_prepare_from_feast_matches_gold_path(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=7, cells=2)
    context = _context_for(frame)
    provinces = _provinces()

    gold = prepare_dataset(
        frame,
        provinces=provinces,
        context=context,
        test_days=2,
        valid_days=2,
        purge_days=1,
        min_train_rows=0,
    )

    tables = build_feature_frames(frame, context, provinces=provinces)
    settings = replace(
        MLSettings.from_env(),
        gold_root=tmp_path,
        feature_cell_root=tmp_path / "cell",
        feature_province_root=tmp_path / "province",
        test_days=2,
        valid_days=2,
        purge_days=1,
        min_train_rows=0,
    )
    _write_partitioned(tables.cells, settings.feature_cell_root)
    _write_partitioned(tables.provinces, settings.feature_province_root)

    feast = prepare_from_feast(
        settings,
        min_train_rows=0,
        feature_store=_FakeStore(tables.cells, tables.provinces),
    )

    assert list(feast.feature_columns) == list(gold.feature_columns)
    assert feast.train.rows == gold.train.rows
    assert feast.valid.rows == gold.valid.rows
    assert feast.test.rows == gold.test.rows
    assert feast.manifest["feature_source"] == "feast"

    left = gold.train.X.copy()
    left["cell_id"] = gold.train.keys["cell_id"].to_numpy()
    left["date"] = gold.train.keys["date"].to_numpy()
    right = feast.train.X.copy()
    right["cell_id"] = feast.train.keys["cell_id"].to_numpy()
    right["date"] = feast.train.keys["date"].to_numpy()
    merged = left.merge(
        right,
        on=["cell_id", "date"],
        suffixes=("_gold", "_feast"),
        validate="one_to_one",
    )
    assert len(merged) == gold.train.rows
    for column in FEATURE_COLUMNS:
        if column == "province":
            assert (
                merged[f"{column}_gold"].astype(str)
                == merged[f"{column}_feast"].astype(str)
            ).all()
        else:
            assert np.allclose(
                pd.to_numeric(merged[f"{column}_gold"], errors="coerce"),
                pd.to_numeric(merged[f"{column}_feast"], errors="coerce"),
                equal_nan=True,
            ), column
