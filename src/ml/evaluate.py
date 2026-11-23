"""Metrik evaluasi biner untuk dataset sel-hari.

Modul ini tidak menyentuh file dan tidak mengimpor ``ml.train`` supaya bisa
dipakai bersama baseline Logistic Regression dan pembanding LightGBM.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


class EvaluationError(ValueError):
    """Input metrik tidak valid."""


def _as_arrays(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
) -> tuple[pd.Series, np.ndarray]:
    y = pd.Series(y_true).reset_index(drop=True)
    if y.isna().any():
        raise EvaluationError("y_true mengandung nilai kosong")
    y = y.astype(int)
    values = np.asarray(proba, dtype=float).reshape(-1)
    if len(y) != len(values):
        raise EvaluationError(f"Panjang y_true ({len(y)}) dan proba ({len(values)}) berbeda")
    if len(y) == 0:
        raise EvaluationError("Input metrik kosong")
    if not np.isfinite(values).all():
        raise EvaluationError("proba mengandung NaN atau inf")
    if not np.isin(y.unique(), [0, 1]).all():
        raise EvaluationError("y_true harus berisi 0 dan 1")
    return y, values


def _require_two_classes(y: pd.Series) -> None:
    if y.nunique() < 2:
        raise EvaluationError("y_true harus memuat dua kelas")


def pr_auc(y_true: Sequence[int] | pd.Series, proba: Sequence[float]) -> float:
    y, values = _as_arrays(y_true, proba)
    _require_two_classes(y)
    return float(average_precision_score(y, values))


def roc_auc(y_true: Sequence[int] | pd.Series, proba: Sequence[float]) -> float:
    y, values = _as_arrays(y_true, proba)
    _require_two_classes(y)
    return float(roc_auc_score(y, values))


def brier(y_true: Sequence[int] | pd.Series, proba: Sequence[float]) -> float:
    y, values = _as_arrays(y_true, proba)
    return float(brier_score_loss(y, values))


def binary_metrics(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    threshold: float,
) -> dict[str, float | int]:
    """Metrik lengkap pada satu ambang."""
    y, values = _as_arrays(y_true, proba)
    _require_two_classes(y)
    if not 0.0 <= float(threshold) <= 1.0:
        raise EvaluationError(f"threshold harus di [0, 1], dapat {threshold}")

    predictions = (values >= float(threshold)).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predictions, labels=[0, 1]).ravel()
    clipped = np.clip(values, 1e-15, 1 - 1e-15)

    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "threshold": float(threshold),
        "pr_auc": float(average_precision_score(y, values)),
        "roc_auc": float(roc_auc_score(y, values)),
        "brier": float(brier_score_loss(y, values)),
        "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
        "precision": float(precision_score(y, predictions, zero_division=0)),
        "recall": float(recall_score(y, predictions, zero_division=0)),
        "f1": float(f1_score(y, predictions, zero_division=0)),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }


def best_threshold(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    *,
    metric: str = "f1",
) -> float:
    """Ambang yang memaksimalkan F1 pada data yang diberikan.

    Hanya mengevaluasi probabilitas yang benar-benar muncul di data. Bila ada
    seri, ambang tertinggi yang dipilih supaya presisi lebih tinggi.
    """
    if metric != "f1":
        raise EvaluationError(f"metric belum didukung: {metric}")
    y, values = _as_arrays(y_true, proba)
    _require_two_classes(y)

    order = np.argsort(-values, kind="mergesort")
    targets = y.to_numpy(dtype=int)[order]
    sorted_proba = values[order]

    true_positive = np.cumsum(targets)
    false_positive = np.cumsum(1 - targets)
    last_of_tie = np.r_[np.flatnonzero(np.diff(sorted_proba) != 0), len(sorted_proba) - 1]

    tp = true_positive[last_of_tie]
    fp = false_positive[last_of_tie]
    thresholds = sorted_proba[last_of_tie]
    fn = tp[-1] - tp

    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / np.maximum(tp + fn, 1)
    denominator = precision + recall
    scores = np.where(denominator > 0, 2 * precision * recall / np.maximum(denominator, 1e-12), 0.0)
    return float(thresholds[int(np.argmax(scores))])


def precision_at_k(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    dates: Sequence[object] | pd.Series,
    *,
    k: int = 100,
) -> float:
    """Rata-rata presisi pada k sel teratas **per tanggal**.

    Metrik operasional: kalau hari itu hanya 100 sel yang bisa diperiksa,
    berapa banyak yang benar-benar terbakar.
    """
    if k < 1:
        raise EvaluationError("k harus >= 1")
    y, values = _as_arrays(y_true, proba)
    day = pd.Series(dates).reset_index(drop=True)
    if len(day) != len(y):
        raise EvaluationError("Panjang dates dan y_true berbeda")

    frame = pd.DataFrame({"target": y.to_numpy(), "proba": values, "date": day})
    scores: list[float] = []
    for _, group in frame.groupby("date", sort=True):
        top = group.nlargest(min(k, len(group)), "proba")
        scores.append(float(top["target"].mean()))
    return float(np.mean(scores))


def calibration_table(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    bins: int = 10,
) -> list[dict[str, float | int]]:
    """Tabel kalibrasi pada bin lebar sama; bin kosong dilewati."""
    if bins < 1:
        raise EvaluationError("bins harus >= 1")
    y, values = _as_arrays(y_true, proba)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(values, edges[1:-1]), 0, bins - 1)
    targets = y.to_numpy(dtype=float)

    rows: list[dict[str, float | int]] = []
    for bucket in range(bins):
        mask = index == bucket
        if not mask.any():
            continue
        rows.append(
            {
                "bin": bucket,
                "lower": float(edges[bucket]),
                "upper": float(edges[bucket + 1]),
                "count": int(mask.sum()),
                "mean_predicted": float(values[mask].mean()),
                "observed": float(targets[mask].mean()),
            }
        )
    return rows


def per_date_metric(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    dates: Sequence[object] | pd.Series,
    *,
    metric: str = "pr_auc",
) -> dict[str, float]:
    """Hitung metrik per tanggal; tanggal dengan satu kelas menjadi NaN."""
    if metric not in {"pr_auc", "roc_auc"}:
        raise EvaluationError(f"metric belum didukung: {metric}")
    y, values = _as_arrays(y_true, proba)
    day = pd.Series(dates).reset_index(drop=True)
    if len(day) != len(y):
        raise EvaluationError("Panjang dates dan y_true berbeda")

    frame = pd.DataFrame({"target": y.to_numpy(), "proba": values, "date": day})
    scorer = pr_auc if metric == "pr_auc" else roc_auc
    result: dict[str, float] = {}
    for date, group in frame.groupby("date", sort=True):
        try:
            result[str(date)] = float(scorer(group["target"], group["proba"]))
        except EvaluationError:
            result[str(date)] = float("nan")
    return result


def paired_bootstrap_delta(
    y_true: Sequence[int] | pd.Series,
    proba_baseline: Sequence[float],
    proba_candidate: Sequence[float],
    dates: Sequence[object] | pd.Series,
    *,
    metric: str = "pr_auc",
    n_resamples: int = 1000,
    seed: int = 42,
) -> dict[str, float | int | str]:
    """Selisih metrik kandidat - baseline dengan bootstrap blok tanggal.

    Resample dilakukan per tanggal, bukan per baris, karena baris dalam satu
    hari saling bergantung.
    """
    if metric not in {"pr_auc", "roc_auc"}:
        raise EvaluationError(f"metric belum didukung: {metric}")
    if n_resamples < 1:
        raise EvaluationError("n_resamples harus >= 1")

    y, baseline = _as_arrays(y_true, proba_baseline)
    _, candidate = _as_arrays(y_true, proba_candidate)
    day = pd.Series(dates).reset_index(drop=True)
    if len(day) != len(y):
        raise EvaluationError("Panjang dates dan y_true berbeda")

    scorer = pr_auc if metric == "pr_auc" else roc_auc
    point = float(scorer(y, candidate) - scorer(y, baseline))

    unique_dates = sorted(day.dropna().unique(), key=str)
    if not unique_dates:
        raise EvaluationError("Tidak ada tanggal untuk bootstrap")
    indices = {date: np.flatnonzero(day.to_numpy() == date) for date in unique_dates}

    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(n_resamples):
        sampled = rng.choice(unique_dates, size=len(unique_dates), replace=True)
        chosen = np.concatenate([indices[date] for date in sampled])
        target = y.to_numpy()[chosen]
        if len(np.unique(target)) < 2:
            continue
        deltas.append(
            float(scorer(target, candidate[chosen]) - scorer(target, baseline[chosen]))
        )

    if not deltas:
        raise EvaluationError("Semua resample hanya punya satu kelas")
    values = np.asarray(deltas, dtype=float)
    return {
        "metric": metric,
        "delta": point,
        "ci_low": float(np.quantile(values, 0.025)),
        "ci_high": float(np.quantile(values, 0.975)),
        "n_resamples": int(len(values)),
        "n_dates": int(len(unique_dates)),
    }


def variance_inflation(matrix: pd.DataFrame) -> pd.Series:
    """VIF dari matriks numerik yang sudah diimputasi.

    Setiap kolom diregresikan pada kolom lain; VIF = 1 / (1 - R²). Kolom
    konstan atau kolinear sempurna menghasilkan ``inf`` supaya bisa dibuang
    pemanggil. Memakai regresi kuadrat terkecil, bukan invers matriks korelasi,
    agar kolinearitas sempurna benar-benar terdeteksi.
    """
    if not isinstance(matrix, pd.DataFrame):
        raise TypeError("matrix harus pandas.DataFrame")
    numeric = matrix.select_dtypes(include=[np.number]).astype(float)
    if numeric.shape[1] == 0:
        return pd.Series(dtype=float)

    values = numeric.to_numpy()
    if not np.isfinite(values).all():
        raise EvaluationError("Matriks VIF harus sudah diimputasi")

    result = pd.Series(np.nan, index=numeric.columns, dtype=float)
    for position, column in enumerate(numeric.columns):
        target = values[:, position]
        spread = float(((target - target.mean()) ** 2).sum())
        if spread <= 0:
            result[column] = np.inf
            continue
        others = np.delete(values, position, axis=1)
        design = np.column_stack([np.ones(len(values)), others])
        coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
        residuals = target - design @ coefficients
        residual_sum = float((residuals**2).sum())
        r_squared = 1.0 - residual_sum / spread
        if r_squared >= 1.0 - 1e-12:
            result[column] = np.inf
        else:
            result[column] = 1.0 / max(1.0 - r_squared, 1e-12)
    return result

