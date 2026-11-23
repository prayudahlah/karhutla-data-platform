from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("joblib")
pytest.importorskip("pyarrow")

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from ml.config import MLSettings  # noqa: E402
from ml.lgbm import (  # noqa: E402
    build_lgbm,
    fit_lgbm,
    importance_frame,
    prepare_categorical,
    tune_lgbm,
)
from ml.train import main, run_lgbm_training  # noqa: E402


def _toy() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(3)
    rows = 60
    frame = pd.DataFrame(
        {
            "n_hotspot": rng.integers(1, 20, rows).astype(float),
            "frp_max": rng.random(rows) * 50,
            "confidence_max": rng.random(rows) * 100,
            "province": pd.Categorical(
                rng.choice(["Riau", "DKI Jakarta"], rows), categories=["Riau", "DKI Jakarta"]
            ),
        }
    )
    target = pd.Series((frame["n_hotspot"] > 8).astype(int))
    train = frame.iloc[:40].reset_index(drop=True)
    valid = frame.iloc[40:].reset_index(drop=True)
    y_train = target.iloc[:40].reset_index(drop=True)
    y_valid = target.iloc[40:].reset_index(drop=True)
    return train, y_train, valid, y_valid


def test_build_lgbm_handles_nan_and_category() -> None:
    train, y_train, valid, y_valid = _toy()
    valid = valid.copy()
    valid.loc[0, "frp_max"] = np.nan

    model = build_lgbm(num_leaves=7, n_estimators=20)
    fit_lgbm(model, train, y_train, valid, y_valid, categorical_columns=["province"])
    proba = model.predict_proba(prepare_categorical(valid, ["province"]))[:, 1]

    assert proba.shape == (len(valid),)
    assert np.isfinite(proba).all()


def test_lgbm_is_deterministic() -> None:
    train, y_train, valid, y_valid = _toy()
    first = build_lgbm(num_leaves=7, n_estimators=20)
    second = build_lgbm(num_leaves=7, n_estimators=20)

    for model in (first, second):
        fit_lgbm(model, train, y_train, valid, y_valid, categorical_columns=["province"])

    a = first.predict_proba(prepare_categorical(valid, ["province"]))[:, 1]
    b = second.predict_proba(prepare_categorical(valid, ["province"]))[:, 1]
    assert np.allclose(a, b, atol=1e-12)


def test_importance_frame() -> None:
    train, y_train, valid, y_valid = _toy()
    model = build_lgbm(num_leaves=7, n_estimators=20)
    fit_lgbm(model, train, y_train, valid, y_valid, categorical_columns=["province"])

    frame = importance_frame(model)
    assert set(frame.columns) >= {"feature", "gain", "split", "rank"}
    assert len(frame) == 4
    assert frame["rank"].min() == 1


def test_tune_lgbm_returns_params_and_results() -> None:
    train, y_train, valid, y_valid = _toy()
    params, results = tune_lgbm(
        train,
        y_train,
        valid,
        y_valid,
        ["province"],
        grid=({"num_leaves": 7, "min_child_samples": 10},),
        extra_feature_fraction=(),
    )

    assert "num_leaves" in params
    assert len(results) == 1
    assert 0.0 <= results[0]["pr_auc"] <= 1.0


def _write_dataset(frame: pd.DataFrame, root: Path) -> Path:
    dataset_root = root / "gold" / "hotspot_cell_day"
    dataset_root.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        dataset_root / "part-0.parquet",
    )
    return dataset_root


def test_run_lgbm_training_end_to_end(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    settings = MLSettings(
        gold_cell_root=dataset_root,
        gold_root=tmp_path / "gold",
        test_days=2,
        valid_days=2,
        purge_days=1,
        min_train_rows=0,
    )

    result = run_lgbm_training(
        settings,
        features="t3",
        out_dir=tmp_path / "model",
        use_mlflow=False,
        test_policy="none",
    )

    output = result["output"]
    for name in (
        "model.joblib",
        "metrics.json",
        "feature_importance.csv",
        "threshold.json",
        "calibration.json",
    ):
        assert (output / name).is_file()

    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert payload["model"] == "lgbm"
    assert payload["test"] is None
    assert payload["test_status"] == "not_evaluated"


def test_lgbm_cli_smoke(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)

    status = main(
        [
            "--model",
            "lgbm",
            "--features",
            "t3",
            "--out",
            str(tmp_path / "cli-model"),
            "--no-mlflow",
            "--no-test",
            "--registry",
            str(tmp_path / "registry.yaml"),
            "--gold-cell-root",
            str(dataset_root),
            "--test-days",
            "2",
            "--valid-days",
            "2",
            "--purge-days",
            "1",
            "--min-train-rows",
            "0",
        ]
    )

    assert status == 0
    assert (tmp_path / "cli-model" / "metrics.json").is_file()
