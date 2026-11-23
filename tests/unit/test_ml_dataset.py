from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from ml.dataset import (  # noqa: E402
    DatasetError,
    assert_label_contract,
    label_fingerprint,
    load_cell_day,
    main,
    prepare_dataset,
    save_manifest,
    split_dates,
)
from ml.province import load_provinces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def _provinces():
    return load_provinces(PROVINCES_CSV)


def test_split_dates_has_purge_and_no_overlap() -> None:
    dates = pd.date_range("2026-01-01", periods=90, freq="D")
    split = split_dates(dates, test_days=10, valid_days=10, purge_days=3)

    assert split.train[-1] < split.valid[0]
    assert split.valid[-1] < split.test[0]
    assert (split.valid[0] - split.train[-1]).days - 1 == 3
    assert (split.test[0] - split.valid[-1]).days - 1 == 3
    assert len(split.test) == 10
    assert len(split.valid) == 10


def test_split_dates_rejects_short_series() -> None:
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    with pytest.raises(DatasetError, match="tidak cukup"):
        split_dates(dates, test_days=10, valid_days=10, purge_days=3)


def test_prepare_dataset_creates_three_splits(cell_factory) -> None:
    frame = cell_factory(days=8, cells=2)
    dataset = prepare_dataset(
        frame,
        provinces=_provinces(),
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=False,
        min_train_rows=0,
    )

    assert dataset.train.rows > 0
    assert dataset.valid.rows > 0
    assert dataset.test.rows > 0
    assert dataset.train.X.shape[1] == len(dataset.feature_columns)
    assert set(dataset.train.y.unique()) <= {0, 1}

    total = dataset.train.rows + dataset.valid.rows + dataset.test.rows
    assert total + dataset.manifest["rows_purged"] == dataset.manifest["rows_complete"]
    assert (
        dataset.manifest["rows_complete"] + dataset.manifest["rows_excluded_incomplete"]
        == len(frame)
    )

    train_dates = sorted(set(dataset.train.keys["date"].dt.date))
    valid_dates = sorted(set(dataset.valid.keys["date"].dt.date))
    test_dates = sorted(set(dataset.test.keys["date"].dt.date))
    assert train_dates[-1] < valid_dates[0]
    assert valid_dates[-1] < test_dates[0]


def test_prepare_dataset_joins_context(
    cell_factory, weather_factory, air_quality_factory
) -> None:
    from ml.features import CONTEXT_COLUMNS, build_daily_context

    context = build_daily_context(
        weather_factory(days=8, start="2026-09-01"),
        air_quality_factory(days=8, start="2026-09-01"),
    )
    dataset = prepare_dataset(
        cell_factory(days=8, cells=1),
        provinces=_provinces(),
        context=context,
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=True,
        min_train_rows=0,
    )
    assert set(CONTEXT_COLUMNS) <= set(dataset.feature_columns)
    assert dataset.train.X["temp_max"].notna().all()


def test_prepare_dataset_rejects_bad_label(cell_factory) -> None:
    frame = cell_factory(days=5)
    frame.loc[0, "label"] = 2
    with pytest.raises(DatasetError, match="label bukan 0/1"):
        prepare_dataset(frame, provinces=_provinces(), include_context=False, min_train_rows=0)


def test_label_contract_rejects_positive_without_confirmation(cell_factory) -> None:
    frame = cell_factory(days=2, cells=1)
    frame.loc[frame.index[0], "label"] = 1
    frame.loc[frame.index[0], "audit_n_confirmed"] = 0

    with pytest.raises(DatasetError, match="kontrak"):
        assert_label_contract(frame)


def test_label_contract_rejects_negative_with_confirmation(cell_factory) -> None:
    frame = cell_factory(days=2, cells=1)
    frame.loc[frame.index[0], "label"] = 0
    frame.loc[frame.index[0], "audit_n_confirmed"] = 2

    with pytest.raises(DatasetError, match="kontrak"):
        assert_label_contract(frame)


def test_label_fingerprint_is_order_independent_and_sensitive(cell_factory) -> None:
    frame = cell_factory(days=3, cells=2)
    baseline = label_fingerprint(frame)

    assert label_fingerprint(frame.sample(frac=1.0, random_state=7)) == baseline

    changed = frame.copy()
    changed.loc[changed.index[0], "label"] = 1 - int(changed.loc[changed.index[0], "label"])
    assert label_fingerprint(changed) != baseline



def test_prepare_dataset_drops_incomplete_rows(cell_factory) -> None:
    frame = cell_factory(days=8, cells=2)
    frame.loc[frame.index[:2], "label_complete"] = False
    dataset = prepare_dataset(
        frame,
        provinces=_provinces(),
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=False,
        min_train_rows=0,
    )
    assert dataset.manifest["rows_excluded_incomplete"] == 2
    assert dataset.manifest["rows_complete"] == len(frame) - 2


def test_prepare_dataset_enforces_min_train_rows(cell_factory) -> None:
    with pytest.raises(DatasetError, match="minimum"):
        prepare_dataset(
            cell_factory(days=8, cells=2),
            provinces=_provinces(),
            test_days=2,
            valid_days=2,
            purge_days=1,
            include_context=False,
            min_train_rows=10_000,
        )


def test_save_manifest_writes_json(cell_factory, tmp_path: Path) -> None:
    dataset = prepare_dataset(
        cell_factory(days=8, cells=2),
        provinces=_provinces(),
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=False,
        min_train_rows=0,
    )
    output = save_manifest(dataset, tmp_path / "split_manifest.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["feature_version"] == dataset.feature_version
    assert payload["label_rule"] == "kuat+sedang"
    assert payload["label_fingerprint"]
    assert payload["splits"]["test"]["rows"] == dataset.test.rows
    assert payload["splits"]["train"]["positive"] + payload["splits"]["train"]["negative"] == (
        dataset.train.rows
    )


def test_load_cell_day_reads_parquet(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=4, cells=2)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), tmp_path / "part-0.parquet")

    loaded = load_cell_day(tmp_path)
    assert len(loaded) == len(frame)
    assert loaded["label"].tolist() == frame["label"].tolist()
    assert pd.api.types.is_datetime64_any_dtype(loaded["date"])


def test_load_cell_day_filters_incomplete(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=4, cells=2)
    frame.loc[frame.index[0], "label_complete"] = False
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), tmp_path / "part-0.parquet")

    loaded = load_cell_day(tmp_path, require_complete=True)
    assert len(loaded) == len(frame) - 1

    everything = load_cell_day(tmp_path, require_complete=False)
    assert len(everything) == len(frame)


def test_load_cell_day_rejects_missing_columns(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=2).drop(columns=["label"])
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), tmp_path / "part-0.parquet")

    with pytest.raises(DatasetError, match="kehilangan kolom"):
        load_cell_day(tmp_path)


def test_dataset_cli_writes_manifest(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=8, cells=2)
    dataset_root = tmp_path / "gold" / "hotspot_cell_day"
    dataset_root.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        dataset_root / "part-0.parquet",
    )

    manifest_path = tmp_path / "split_manifest.json"
    status = main(
        [
            "--gold-cell-root",
            str(dataset_root),
            "--out",
            str(manifest_path),
            "--provinces",
            str(PROVINCES_CSV),
            "--test-days",
            "2",
            "--valid-days",
            "2",
            "--purge-days",
            "1",
            "--min-train-rows",
            "0",
            "--no-context",
        ]
    )

    assert status == 0
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["splits"]["train"]["rows"] > 0
    assert payload["splits"]["test"]["rows"] > 0
    assert "per_day_positive_share" in payload


def test_load_cell_day_allows_null_label_only_for_incomplete(
    cell_factory, tmp_path: Path
) -> None:
    frame = cell_factory(days=4, cells=2)
    frame["label"] = frame["label"].astype("Int64")
    frame.loc[0, "label"] = pd.NA
    frame.loc[0, "label_complete"] = False
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        tmp_path / "part-0.parquet",
    )

    everything = load_cell_day(tmp_path, require_complete=False)
    assert len(everything) == len(frame)
    assert everything.loc[0, "label"] is pd.NA or pd.isna(everything.loc[0, "label"])

    complete = load_cell_day(tmp_path, require_complete=True)
    assert len(complete) == len(frame) - 1
    assert complete["label"].notna().all()


def test_load_cell_day_rejects_null_label_when_complete(
    cell_factory, tmp_path: Path
) -> None:
    frame = cell_factory(days=2, cells=1)
    frame["label"] = frame["label"].astype("Int64")
    frame.loc[0, "label"] = pd.NA
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        tmp_path / "part-0.parquet",
    )

    with pytest.raises(DatasetError, match="label bukan 0/1"):
        load_cell_day(tmp_path, require_complete=False)
