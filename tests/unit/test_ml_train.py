from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("joblib")
pytest.importorskip("pyarrow")

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import yaml  # noqa: E402

from ml.config import MLSettings  # noqa: E402
from ml.dataset import prepare_dataset  # noqa: E402
from ml.regions import LOCATION_FEATURES, region_of  # noqa: E402
from ml.train import (  # noqa: E402
    TrainingError,
    assert_freeze_matches,
    assert_test_budget,
    build_lr_pipeline,
    coefficients_frame,
    filter_holdout_region,
    load_freeze_config,
    main,
    run_training,
    select_features,
    threshold_for_precision,
    vif_filter,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _toy_frame() -> tuple[pd.DataFrame, pd.Series]:
    frame = pd.DataFrame(
        {
            "n_hotspot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "frp_max": [0.0, 1.0, 0.0, 2.0, 3.0, 4.0],
            "confidence_max": [60.0, np.nan, 90.0, 70.0, np.nan, 80.0],
            "province": pd.Categorical(
                ["Riau", "DKI Jakarta", "Riau", "DKI Jakarta", "Riau", "DKI Jakarta"],
                categories=["Riau", "DKI Jakarta"],
            ),
        }
    )
    target = pd.Series([0, 1, 0, 1, 0, 1])
    return frame, target


def test_log1p_branch_is_safe_for_zero_and_nan() -> None:
    frame, target = _toy_frame()
    pipeline = build_lr_pipeline(list(frame.columns), ["province"], c=1.0)
    pipeline.fit(frame, target)

    transformed = pipeline.named_steps["pre"].transform(frame)
    assert np.isfinite(transformed).all()


def test_unknown_province_is_ignored_at_predict() -> None:
    frame, target = _toy_frame()
    pipeline = build_lr_pipeline(list(frame.columns), ["province"], c=1.0)
    pipeline.fit(frame, target)

    unseen = frame.copy()
    unseen["province"] = pd.Categorical(
        ["Atlantis"] * len(frame), categories=["Atlantis"]
    )
    proba = pipeline.predict_proba(unseen)
    assert proba.shape == (len(frame), 2)


def test_coefficients_align_with_transformed_features() -> None:
    frame, target = _toy_frame()
    pipeline = build_lr_pipeline(list(frame.columns), ["province"], c=1.0)
    pipeline.fit(frame, target)

    names = pipeline.named_steps["pre"].get_feature_names_out()
    table = coefficients_frame(pipeline)
    assert len(table) == len(names)
    assert (table["odds_ratio"] > 0).all()
    assert set(table["feature"]) == set(names)


def test_select_features_respects_groups() -> None:
    columns = ("n_hotspot", "frp_max", "center_lat", "province", "temp_max")

    assert select_features(columns, "nhotspot") == ["n_hotspot"]
    assert select_features(columns, "t1") == ["center_lat", "province", "temp_max"]
    assert select_features(columns, "t2") == [
        "frp_max",
        "center_lat",
        "province",
        "temp_max",
    ]
    assert select_features(columns, "t3") == list(columns)

    with_region = (*columns, "region")
    selected = select_features(with_region, "t3r")
    assert "region" in selected
    assert "province" not in selected


def test_vif_filter_drops_collinear_feature() -> None:
    frame = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
            "c": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        }
    )
    kept, dropped = vif_filter(frame, ["a", "b", "c"])
    assert dropped
    assert len(kept) == 2


def test_vif_filter_protects_n_hotspot() -> None:
    frame = pd.DataFrame(
        {
            "n_hotspot": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "n_night": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
            "frp_max": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        }
    )
    kept, dropped = vif_filter(frame, ["n_hotspot", "n_night", "frp_max"])

    assert "n_hotspot" in kept
    assert any(item["feature"] == "n_night" for item in dropped)


def test_threshold_for_precision_returns_valid_probability() -> None:
    target = pd.Series([0, 0, 1, 1])
    proba = np.array([0.1, 0.4, 0.6, 0.9])
    threshold = threshold_for_precision(target, proba, target=0.5)
    assert threshold in set(proba.tolist())


def _write_registry(path: Path, *, looks: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "families": {
                    "lr-baseline": {
                        "test_window": ["2026-09-07", "2026-09-08"],
                        "test_looks": looks,
                        "sealed": False,
                    }
                },
                "runs": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_dataset(frame: pd.DataFrame, root: Path) -> Path:
    dataset_root = root / "gold" / "hotspot_cell_day"
    dataset_root.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        dataset_root / "part-0.parquet",
    )
    return dataset_root


def _settings(dataset_root: Path, gold_root: Path) -> MLSettings:
    return MLSettings(
        gold_cell_root=dataset_root,
        gold_root=gold_root,
        test_days=2,
        valid_days=2,
        purge_days=1,
        min_train_rows=0,
    )


def test_run_training_end_to_end(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    settings = _settings(dataset_root, tmp_path / "gold")

    result = run_training(
        settings,
        features="t3",
        out_dir=tmp_path / "model",
        use_mlflow=False,
        c_grid=(1.0,),
    )

    output = result["output"]
    for name in (
        "pipeline.joblib",
        "metrics.json",
        "coefficients.csv",
        "threshold.json",
        "calibration.json",
    ):
        assert (output / name).is_file()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import joblib; joblib.load(r'{output / 'pipeline.joblib'}')",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert check.returncode == 0, check.stderr

    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert payload["label_rule"] == "kuat+sedang"
    assert payload["label_horizon_days"] == 7
    assert 0.0 <= payload["threshold"] <= 1.0
    assert payload["test_rows"] > 0
    assert payload["test"]["pr_auc"] >= 0.0
    assert "dropped_vif" in payload


def test_train_cli_smoke(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    registry = _write_registry(tmp_path / "registry.yaml")

    status = main(
        [
            "--features",
            "t3",
            "--registry",
            str(registry),
            "--out",
            str(tmp_path / "cli-model"),
            "--no-mlflow",
            "--c-grid",
            "1.0",
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


def test_test_budget_refuses_seen_window(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "registry.yaml", looks=1)

    with pytest.raises(TrainingError, match="sudah dievaluasi"):
        assert_test_budget(registry, "lr-baseline", ["2026-09-07", "2026-09-08"])

    assert_test_budget(
        registry,
        "lr-baseline",
        ["2026-09-07", "2026-09-08"],
        allow_seen=True,
    )


def test_test_budget_rejects_other_window(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "registry.yaml")

    with pytest.raises(TrainingError, match="tidak cocok"):
        assert_test_budget(registry, "lr-baseline", ["2026-10-01", "2026-10-05"])


def test_no_test_run_skips_test_metrics(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    settings = _settings(dataset_root, tmp_path / "gold")

    result = run_training(
        settings,
        features="t3",
        out_dir=tmp_path / "model",
        use_mlflow=False,
        c_grid=(1.0,),
        test_policy="none",
    )

    payload = result["payload"]
    assert payload["test"] is None
    assert payload["precision_at_100_test"] is None
    assert payload["test_status"] == "not_evaluated"


def test_freeze_config_must_match() -> None:
    config = {"id": "demo", "feature_group": "t3", "c": 10.0, "class_weight": None}

    assert_freeze_matches(config, features="t3", c=10.0, class_weight=None)

    with pytest.raises(TrainingError, match="tidak cocok"):
        assert_freeze_matches(config, features="t3", c=1.0, class_weight=None)


def test_load_freeze_config_hashes_file(tmp_path: Path) -> None:
    path = tmp_path / "freeze.yaml"
    path.write_text("id: demo\nfeature_group: t3\nc: 10.0\nclass_weight: null\n", encoding="utf-8")

    config = load_freeze_config(path)
    assert config["id"] == "demo"
    assert len(str(config["_sha256"])) == 64


def test_holdout_region_moves_region_to_test(cell_factory) -> None:
    dataset = prepare_dataset(
        cell_factory(days=8, cells=2),
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=False,
        min_train_rows=0,
    )

    filtered = filter_holdout_region(dataset, "Jawa")

    assert {region_of(p) for p in filtered.train.keys["province"].astype(str)} == {"Sumatra"}
    assert {region_of(p) for p in filtered.valid.keys["province"].astype(str)} == {"Sumatra"}
    assert {region_of(p) for p in filtered.test.keys["province"].astype(str)} == {"Jawa"}
    assert set(filtered.test.keys["cell_id"]).isdisjoint(
        set(filtered.train.keys["cell_id"]) | set(filtered.valid.keys["cell_id"])
    )


def test_holdout_region_rejects_unknown(cell_factory) -> None:
    dataset = prepare_dataset(
        cell_factory(days=8, cells=2),
        test_days=2,
        valid_days=2,
        purge_days=1,
        include_context=False,
        min_train_rows=0,
    )

    with pytest.raises(Exception, match="tidak dikenal"):
        filter_holdout_region(dataset, "Atlantis")


def test_run_training_with_holdout_and_location_ablation(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    settings = _settings(dataset_root, tmp_path / "gold")

    result = run_training(
        settings,
        features="t3",
        out_dir=tmp_path / "spatial",
        use_mlflow=False,
        c_grid=(1.0,),
        holdout_region="Jawa",
        drop_location_features=True,
        test_policy="none",
    )

    payload = result["payload"]
    assert payload["holdout_region"] == "Jawa"
    assert payload["drop_location_features"] is True
    assert set(payload["feature_columns"]).isdisjoint(LOCATION_FEATURES)
    assert set(payload["test_window"]) == {"2026-09-07", "2026-09-08"}


def test_run_training_with_region_grouping(cell_factory, tmp_path: Path) -> None:
    dataset_root = _write_dataset(cell_factory(days=8, cells=2), tmp_path)
    settings = _settings(dataset_root, tmp_path / "gold")

    result = run_training(
        settings,
        features="t3r",
        out_dir=tmp_path / "region",
        use_mlflow=False,
        c_grid=(1.0,),
        test_policy="none",
    )

    payload = result["payload"]
    assert payload["region_grouping"] is True
    assert "region" in payload["feature_columns"]
    assert "province" not in payload["feature_columns"]
