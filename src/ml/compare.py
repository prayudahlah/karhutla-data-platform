"""Bandingkan dua model temporal di valid dengan bootstrap blok tanggal.

Dipakai pipeline Prefect untuk memutuskan rekomendasi champion. Test tidak
disentuh: jendela 19-23 September sudah ``seen``, jadi semua angka di sini
adalah angka valid.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ml.evaluate import brier, paired_bootstrap_delta, per_date_metric, pr_auc


@dataclass(frozen=True)
class PredictionSet:
    """Prediksi valid satu model beserta payload metriknya."""

    name: str
    predictions: pd.DataFrame
    payload: Mapping[str, Any]


def _aligned(baseline: PredictionSet, candidate: PredictionSet) -> pd.DataFrame:
    left = baseline.predictions.rename(
        columns={"label": "label_baseline", "proba": "proba_baseline"}
    )
    right = candidate.predictions.rename(columns={"proba": "proba_candidate"})
    merged = left.merge(
        right[["cell_id", "date", "label", "proba_candidate"]],
        on=["cell_id", "date"],
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise ValueError("Tidak ada baris valid yang bisa dibandingkan")
    if (merged["label_baseline"] != merged["label"]).any():
        raise ValueError("Label baseline dan kandidat berbeda pada baris yang sama")
    return merged.sort_values(["date", "cell_id"]).reset_index(drop=True)


def compare_models(
    baseline: PredictionSet,
    candidate: PredictionSet,
    *,
    criteria: Mapping[str, Any],
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Hitung delta PR-AUC, CI bootstrap, Brier, dan keputusan promosi."""
    frame = _aligned(baseline, candidate)
    y = frame["label_baseline"].astype(int)
    dates = frame["date"]
    baseline_proba = frame["proba_baseline"].astype(float)
    candidate_proba = frame["proba_candidate"].astype(float)

    metric = str(criteria.get("metric", "pr_auc"))
    bootstrap = paired_bootstrap_delta(
        y,
        baseline_proba,
        candidate_proba,
        dates,
        metric=metric,
        n_resamples=int(criteria.get("n_resamples", 1000)),
    )
    baseline_pr = pr_auc(y, baseline_proba)
    candidate_pr = pr_auc(y, candidate_proba)
    baseline_brier = brier(y, baseline_proba)
    candidate_brier = brier(y, candidate_proba)

    baseline_daily = per_date_metric(y, baseline_proba, dates, metric=metric)
    candidate_daily = per_date_metric(y, candidate_proba, dates, metric=metric)
    days_better = sum(
        1
        for day, value in candidate_daily.items()
        if pd.notna(value)
        and pd.notna(baseline_daily.get(day))
        and value > baseline_daily[day]
    )
    days_compared = sum(
        1 for day, value in candidate_daily.items() if pd.notna(value)
    )

    delta_pr = float(candidate_pr - baseline_pr)
    delta_brier = float(candidate_brier - baseline_brier)
    min_delta = float(criteria.get("min_delta", 0.01))
    require_ci = bool(criteria.get("require_ci_low_positive", True))
    min_days = int(criteria.get("min_days_better", 3))
    max_brier_worse = float(criteria.get("max_brier_worse", 0.01))

    accepted = (
        delta_pr >= min_delta
        and (not require_ci or float(bootstrap["ci_low"]) > 0.0)
        and days_better >= min_days
        and delta_brier <= max_brier_worse
    )

    result: dict[str, Any] = {
        "baseline": {
            "name": baseline.name,
            "model": baseline.payload.get("model"),
            "valid": dict(baseline.payload.get("valid") or {}),
            "feature_count": len(baseline.payload.get("feature_columns") or []),
        },
        "candidate": {
            "name": candidate.name,
            "model": candidate.payload.get("model"),
            "valid": dict(candidate.payload.get("valid") or {}),
            "feature_count": len(candidate.payload.get("feature_columns") or []),
        },
        "delta_valid": {
            **dict(bootstrap),
            "delta": delta_pr,
            "brier_delta": delta_brier,
        },
        "days_better": days_better,
        "days_compared": days_compared,
        "criteria": {
            "metric": metric,
            "min_delta": min_delta,
            "require_ci_low_positive": require_ci,
            "min_days_better": min_days,
            "max_brier_worse": max_brier_worse,
        },
        "decision": "accepted" if accepted else "rejected",
        "recommended": candidate.name if accepted else baseline.name,
        "test_status": "not_evaluated",
        "caveat": (
            "Perbandingan hanya memakai valid. Jendela test 19-23 September 2026 "
            "berstatus seen dan tidak dipakai untuk memilih konfigurasi."
        ),
    }

    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result["artifact"] = str(path)
    return result
