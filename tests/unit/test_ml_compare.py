from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("scikit-learn")

import pandas as pd  # noqa: E402

from ml.compare import PredictionSet, compare_models  # noqa: E402


def _predictions(proba_by_day: list[float]) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-09-11", periods=len(proba_by_day), freq="D")
    for date, strength in zip(dates, proba_by_day, strict=True):
        labels = [1, 1, 0, 0]
        probas = [min(strength + 0.2, 0.99), min(strength + 0.1, 0.99), 0.2, 0.1]
        for index, (label, proba) in enumerate(zip(labels, probas, strict=True)):
            rows.append(
                {
                    "cell_id": f"cell-{index}",
                    "date": date,
                    "label": label,
                    "proba": proba,
                }
            )
    return pd.DataFrame(rows)


def _payload(name: str, pr_auc: float, brier: float):
    return {
        "model": name,
        "valid": {"pr_auc": pr_auc, "brier": brier},
        "feature_columns": ["a", "b"],
    }


def test_compare_accepts_clear_candidate(tmp_path: Path) -> None:
    baseline = PredictionSet(
        "lr",
        _predictions([0.2, 0.2, 0.2, 0.2, 0.2]),
        _payload("lr", 0.6, 0.1),
    )
    candidate = PredictionSet(
        "lgbm",
        _predictions([0.7, 0.7, 0.7, 0.7, 0.7]),
        _payload("lgbm", 0.8, 0.08),
    )
    output = tmp_path / "comparison.json"
    result = compare_models(
        baseline,
        candidate,
        criteria={
            "metric": "pr_auc",
            "min_delta": 0.01,
            "require_ci_low_positive": True,
            "min_days_better": 3,
            "max_brier_worse": 0.01,
            "n_resamples": 50,
        },
        output=output,
    )

    assert result["decision"] == "accepted"
    assert result["recommended"] == "lgbm"
    assert result["days_better"] == 5
    assert result["delta_valid"]["delta"] > 0
    assert json.loads(output.read_text(encoding="utf-8"))["decision"] == "accepted"


def test_compare_rejects_candidate_with_worse_brier() -> None:
    baseline = PredictionSet(
        "lr",
        _predictions([0.5, 0.5, 0.5, 0.5, 0.5]),
        _payload("lr", 0.7, 0.05),
    )
    candidate = PredictionSet(
        "lgbm",
        _predictions([0.55, 0.55, 0.55, 0.55, 0.55]),
        _payload("lgbm", 0.72, 0.20),
    )
    result = compare_models(
        baseline,
        candidate,
        criteria={
            "metric": "pr_auc",
            "min_delta": 0.01,
            "require_ci_low_positive": True,
            "min_days_better": 3,
            "max_brier_worse": 0.01,
            "n_resamples": 50,
        },
    )

    assert result["decision"] == "rejected"
    assert result["recommended"] == "lr"
    assert result["delta_valid"]["brier_delta"] > 0.01
