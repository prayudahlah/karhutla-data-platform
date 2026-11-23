from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("numpy")
pytest.importorskip("pandas")

from ml.evaluate import (  # noqa: E402
    EvaluationError,
    best_threshold,
    binary_metrics,
    brier,
    calibration_table,
    paired_bootstrap_delta,
    per_date_metric,
    pr_auc,
    precision_at_k,
    roc_auc,
    variance_inflation,
)


def _perfect() -> tuple[pd.Series, np.ndarray]:
    y = pd.Series([0, 0, 1, 1])
    proba = np.array([0.1, 0.2, 0.8, 0.9])
    return y, proba


def test_perfect_predictions() -> None:
    y, proba = _perfect()
    assert pr_auc(y, proba) == pytest.approx(1.0)
    assert roc_auc(y, proba) == pytest.approx(1.0)
    assert brier(y, proba) == pytest.approx(0.025)

    metrics = binary_metrics(y, proba, 0.5)
    assert metrics["f1"] == pytest.approx(1.0)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["tp"] == 2
    assert metrics["tn"] == 2


def test_single_class_is_rejected() -> None:
    with pytest.raises(EvaluationError, match="dua kelas"):
        pr_auc(pd.Series([1, 1, 1]), np.array([0.2, 0.3, 0.4]))


def test_length_mismatch_is_rejected() -> None:
    with pytest.raises(EvaluationError, match="berbeda"):
        binary_metrics(pd.Series([0, 1]), np.array([0.1, 0.2, 0.3]), 0.5)


def test_best_threshold_uses_observed_probability() -> None:
    y = pd.Series([0, 0, 1, 1, 0, 1])
    proba = np.array([0.05, 0.15, 0.55, 0.65, 0.35, 0.45])
    threshold = best_threshold(y, proba)

    assert threshold in set(proba.tolist())
    assert binary_metrics(y, proba, threshold)["f1"] >= binary_metrics(y, proba, 0.5)["f1"]


def test_precision_at_k_is_per_date() -> None:
    dates = ["2026-09-01"] * 3 + ["2026-09-02"] * 3
    # Hari 1: dua teratas benar. Hari 2: tidak ada yang benar.
    y = pd.Series([1, 1, 0, 1, 0, 0])
    proba = np.array([0.9, 0.8, 0.1, 0.2, 0.3, 0.4])

    assert precision_at_k(y, proba, dates, k=2) == pytest.approx((1.0 + 0.0) / 2)


def test_calibration_table_bins() -> None:
    y = pd.Series([0, 0, 1, 1])
    proba = np.array([0.05, 0.15, 0.85, 0.95])
    rows = calibration_table(y, proba, bins=10)

    assert 0 < len(rows) <= 10
    assert sum(row["count"] for row in rows) == 4
    assert all(0.0 <= row["observed"] <= 1.0 for row in rows)


def test_vif_flags_collinear_and_constant_columns() -> None:
    frame = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0],
            "c": [1.0, 0.0, 1.0, 0.0, 1.0],
            "const": [5.0, 5.0, 5.0, 5.0, 5.0],
        }
    )
    values = variance_inflation(frame)

    assert np.isinf(values["a"]) or np.isinf(values["b"])
    assert np.isinf(values["const"])


def test_vif_requires_imputed_matrix() -> None:
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [1.0, 2.0, 3.0]})
    with pytest.raises(EvaluationError, match="diimputasi"):
        variance_inflation(frame)


def test_per_date_metric_returns_each_date() -> None:
    dates = ["2026-09-01"] * 3 + ["2026-09-02"] * 3
    y = pd.Series([1, 1, 0, 1, 0, 0])
    proba = np.array([0.9, 0.8, 0.1, 0.2, 0.3, 0.4])

    values = per_date_metric(y, proba, dates)
    assert set(values) == {"2026-09-01", "2026-09-02"}
    assert values["2026-09-01"] == pytest.approx(1.0)


def test_paired_bootstrap_delta_detects_better_candidate() -> None:
    rng = np.random.default_rng(7)
    days = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    dates = [day for day in days for _ in range(60)]
    y = pd.Series([1 if rng.random() < 0.2 else 0 for _ in range(len(dates))])
    baseline = np.clip(y * 0.3 + rng.random(len(dates)) * 0.5, 0, 1)
    candidate = np.clip(y * 0.6 + rng.random(len(dates)) * 0.4, 0, 1)

    result = paired_bootstrap_delta(y, baseline, candidate, dates, n_resamples=200)

    assert result["delta"] > 0
    assert result["ci_low"] <= result["delta"] <= result["ci_high"]
    assert result["n_dates"] == 4
    assert result["n_resamples"] > 100
