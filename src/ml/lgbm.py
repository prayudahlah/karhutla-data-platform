"""LightGBM sebagai model pembanding Logistic Regression.

Modul ini hanya berisi model dan tuning. Orkestrasi dataset, registry, dan
MLflow ada di ``ml.train`` supaya kedua model memakai jalur yang sama.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation

LGBM_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "metric": "average_precision",
    "learning_rate": 0.03,
    "n_estimators": 2000,
    "num_leaves": 31,
    "min_child_samples": 30,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "scale_pos_weight": 1,
    "random_state": 42,
    "deterministic": True,
    "force_col_wise": True,
    "n_jobs": 4,
    "verbose": -1,
}

EARLY_STOPPING_ROUNDS = 50
TUNING_KEYS = ("num_leaves", "min_child_samples", "feature_fraction", "learning_rate", "lambda_l2")

DEFAULT_GRID: tuple[dict[str, Any], ...] = tuple(
    {"num_leaves": leaves, "min_child_samples": samples}
    for leaves in (15, 31, 63)
    for samples in (20, 50)
)


class LgbmError(RuntimeError):
    """Konfigurasi LightGBM tidak valid."""


def build_lgbm(**overrides: Any) -> LGBMClassifier:
    params = {**LGBM_PARAMS, **overrides}
    return LGBMClassifier(**params)


def prepare_categorical(
    frame: pd.DataFrame,
    categorical_columns: Sequence[str],
) -> pd.DataFrame:
    """Pastikan kolom kategorikal bertipe pandas category untuk LightGBM."""
    result = frame.copy()
    for column in categorical_columns:
        if column in result.columns:
            result[column] = result[column].astype("category")
    return result


def fit_lgbm(
    model: LGBMClassifier,
    train_features: pd.DataFrame,
    train_target: pd.Series,
    valid_features: pd.DataFrame,
    valid_target: pd.Series,
    *,
    categorical_columns: Sequence[str] = ("province",),
) -> LGBMClassifier:
    model.fit(
        prepare_categorical(train_features, categorical_columns),
        train_target,
        eval_set=[
            (
                prepare_categorical(valid_features, categorical_columns),
                valid_target,
            )
        ],
        callbacks=[
            early_stopping(EARLY_STOPPING_ROUNDS, verbose=False),
            log_evaluation(0),
        ],
    )
    return model


def importance_frame(model: LGBMClassifier) -> pd.DataFrame:
    booster = model.booster_
    frame = pd.DataFrame(
        {
            "feature": booster.feature_name(),
            "gain": booster.feature_importance(importance_type="gain"),
            "split": booster.feature_importance(importance_type="split"),
        }
    )
    frame["rank"] = frame["gain"].rank(ascending=False, method="min").astype(int)
    return frame.sort_values("rank").reset_index(drop=True)


def tune_lgbm(
    train_features: pd.DataFrame,
    train_target: pd.Series,
    valid_features: pd.DataFrame,
    valid_target: pd.Series,
    categorical_columns: Sequence[str],
    *,
    grid: Sequence[Mapping[str, Any]] = DEFAULT_GRID,
    extra_feature_fraction: Sequence[float] = (0.6, 1.0),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cari hyperparameter di valid dengan PR-AUC; seri diputus Brier."""
    from ml.evaluate import brier, pr_auc

    results: list[dict[str, Any]] = []

    def evaluate(params: Mapping[str, Any]) -> dict[str, Any]:
        model = build_lgbm(**dict(params))
        fit_lgbm(
            model,
            train_features,
            train_target,
            valid_features,
            valid_target,
            categorical_columns=categorical_columns,
        )
        proba = model.predict_proba(
            prepare_categorical(valid_features, categorical_columns)
        )[:, 1]
        record = {
            **{key: LGBM_PARAMS[key] for key in TUNING_KEYS if key in LGBM_PARAMS},
            **dict(params),
            "best_iteration": int(model.best_iteration_ or model.n_estimators),
            "pr_auc": pr_auc(valid_target, proba),
            "brier": brier(valid_target, proba),
        }
        results.append(record)
        return record

    for params in grid:
        evaluate(params)

    best = min(results, key=lambda item: (-item["pr_auc"], item["brier"]))
    best_params = {key: best[key] for key in TUNING_KEYS if key in best}

    for fraction in extra_feature_fraction:
        candidate = {**best_params, "feature_fraction": float(fraction)}
        record = evaluate(candidate)
        if (record["pr_auc"], -record["brier"]) > (best["pr_auc"], -best["brier"]):
            best = record
            best_params = {key: best[key] for key in TUNING_KEYS if key in best}

    return best_params, results


def assert_lgbm_freeze_matches(
    config: Mapping[str, Any],
    *,
    features: str,
    vif: bool,
    params: Mapping[str, Any],
) -> None:
    """Pastikan run memakai konfigurasi LightGBM yang sama dengan berkas beku."""
    if str(config.get("feature_group")) != features:
        raise LgbmError(
            f"features {features} tidak cocok dengan konfigurasi beku {config.get('feature_group')}"
        )
    if bool(config.get("vif", False)) != bool(vif):
        raise LgbmError(
            f"vif {vif} tidak cocok dengan konfigurasi beku {config.get('vif')}"
        )
    expected = config.get("params") or {}
    for key in TUNING_KEYS:
        if key not in expected:
            continue
        if abs(float(expected[key]) - float(params.get(key, expected[key]))) > 1e-12:
            raise LgbmError(f"{key} tidak cocok dengan konfigurasi beku")
