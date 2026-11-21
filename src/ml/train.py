"""Latih baseline Logistic Regression dari Gold ``hotspot_cell_day``.

Pipeline disimpan utuh (imputer + log1p + scaler + one-hot + model) supaya
inference tidak bisa menyimpang dari training. Label tidak pernah dihitung
ulang di sini; modul ini hanya membaca kolom ``label`` yang sudah ditetapkan
dbt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from common.config import load_dotenv
from common.run import utc_now_iso
from ml.config import MLSettings
from ml.dataset import DatasetError, PreparedDataset, SplitData, prepare_from_settings
from ml.evaluate import (
    EvaluationError,
    best_threshold,
    binary_metrics,
    brier,
    calibration_table,
    pr_auc,
    precision_at_k,
    variance_inflation,
)
from ml.features import CELL_FEATURE_GROUPS, CELL_HISTORY_COLUMNS
from ml.lgbm import (
    DEFAULT_GRID,
    LgbmError,
    assert_lgbm_freeze_matches,
    build_lgbm,
    fit_lgbm,
    importance_frame,
    prepare_categorical,
    tune_lgbm,
)
from ml.regions import (
    ALL_REGIONS,
    LOCATION_FEATURES,
    PROVINCE_TO_REGION,
    region_slug,
    validate_regions,
)
from ml.transformers import stringify_categorical

LOG_COLUMNS: tuple[str, ...] = (
    "n_hotspot",
    "n_night",
    "n_satellite",
    "frp_max",
    "frp_mean",
    "frp_p95",
    "scan_max",
    "track_max",
)

C_GRID: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0)
VIF_LIMIT = 10.0
PROTECTED_FEATURES: frozenset[str] = frozenset({"n_hotspot"})
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "experiments" / "registry.yaml"
TEST_POLICIES: tuple[str, ...] = ("sealed", "seen", "none")
TARGET_PRECISION = 0.5

_GROUPS = CELL_FEATURE_GROUPS
_T1 = frozenset(_GROUPS["context"]) | frozenset(_GROUPS["static"])
_T2 = _T1 | frozenset(_GROUPS["intensity"])
_T3 = _T2 | frozenset(_GROUPS["density"])

SELECTION_GROUPS: dict[str, frozenset[str]] = {
    "nhotspot": frozenset({"n_hotspot"}),
    "t1": _T1,
    "t2": _T2,
    "t3": _T3,
    "t3h": _T3 | frozenset(_GROUPS["history"]),
    "t3r": (_T3 - {"province"}) | {"region"},
}


class TrainingError(RuntimeError):
    """Training tidak bisa dijalankan dengan konfigurasi ini."""


def select_features(feature_columns: Sequence[str], group: str) -> list[str]:
    """Pilih subset fitur menurut grup ablasi, mempertahankan urutan asli."""
    if group not in SELECTION_GROUPS:
        raise TrainingError(f"grup fitur tidak dikenal: {group}")
    allowed = SELECTION_GROUPS[group]
    selected = [column for column in feature_columns if column in allowed]
    if not selected:
        raise TrainingError(f"grup {group} tidak menghasilkan fitur")
    return selected


def build_lr_pipeline(
    feature_columns: Sequence[str],
    categorical_columns: Sequence[str],
    *,
    c: float = 1.0,
    class_weight: str | None = None,
) -> Pipeline:
    """Pipeline LR: log1p untuk fitur miring, scaling, one-hot provinsi."""
    categorical = [column for column in categorical_columns if column in feature_columns]
    numeric = [column for column in feature_columns if column not in categorical]
    logged = [column for column in numeric if column in LOG_COLUMNS]
    plain = [column for column in numeric if column not in LOG_COLUMNS]

    transformers: list[tuple[str, Any, list[str]]] = []
    if logged:
        transformers.append(
            (
                "log",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
                        ("scale", StandardScaler()),
                    ]
                ),
                logged,
            )
        )
    if plain:
        transformers.append(
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                plain,
            )
        )
    if categorical:
        transformers.append(
            (
                "cat",
                Pipeline(
                    [
                        (
                            "stringify",
                            FunctionTransformer(
                                stringify_categorical, feature_names_out="one-to-one"
                            ),
                        ),
                        (
                            "onehot",
                            OneHotEncoder(
                                drop="first",
                                handle_unknown="ignore",
                                sparse_output=False,
                            ),
                        ),
                    ]
                ),
                categorical,
            )
        )

    preprocessing = ColumnTransformer(
        transformers,
        remainder="drop",
        verbose_feature_names_out=True,
    )
    classifier = LogisticRegression(
        C=float(c),
        solver="lbfgs",
        class_weight=class_weight,
        max_iter=3000,
        random_state=42,
    )
    return Pipeline([("pre", preprocessing), ("clf", classifier)])


def _imputed(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    values = SimpleImputer(strategy="median").fit_transform(frame[list(columns)])
    return pd.DataFrame(values, columns=list(columns))


def vif_filter(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    limit: float = VIF_LIMIT,
    protected: frozenset[str] = PROTECTED_FEATURES,
) -> tuple[list[str], list[dict[str, float | str]]]:
    """Buang fitur dengan VIF di atas batas, satu per satu, nilai terbesar dulu.

    ``n_hotspot`` dilindungi karena merupakan fitur operasional utama. Bila
    fitur itu kolinear, yang dibuang adalah pasangannya, bukan fiturnya.
    """
    remaining = list(columns)
    dropped: list[dict[str, float | str]] = []
    while len(remaining) > 1:
        values = variance_inflation(_imputed(frame, remaining))
        candidates = [column for column in remaining if column not in protected]
        if not candidates:
            break
        worst = str(max(candidates, key=lambda column: float(values.loc[column])))
        worst_value = float(values.loc[worst])
        if np.isfinite(worst_value) and worst_value <= limit:
            break
        dropped.append({"feature": worst, "vif": worst_value})
        remaining.remove(worst)
    return remaining, dropped


def threshold_for_precision(
    y_true: Sequence[int] | pd.Series,
    proba: Sequence[float],
    *,
    target: float = TARGET_PRECISION,
) -> float:
    """Ambang terendah yang masih memenuhi presisi target (recall maksimum)."""
    y = pd.Series(y_true).reset_index(drop=True).astype(int)
    values = np.asarray(proba, dtype=float).reshape(-1)
    order = np.argsort(-values, kind="mergesort")
    targets = y.to_numpy()[order]
    sorted_proba = values[order]
    true_positive = np.cumsum(targets)
    false_positive = np.cumsum(1 - targets)
    last_of_tie = np.r_[np.flatnonzero(np.diff(sorted_proba) != 0), len(sorted_proba) - 1]

    tp = true_positive[last_of_tie]
    fp = false_positive[last_of_tie]
    precision = tp / np.maximum(tp + fp, 1)
    eligible = np.flatnonzero(precision >= target)
    if eligible.size == 0:
        return 1.0
    return float(sorted_proba[last_of_tie][eligible[-1]])


def tune_c(
    dataset: PreparedDataset,
    feature_columns: Sequence[str],
    categorical_columns: Sequence[str],
    *,
    c_grid: Sequence[float] = C_GRID,
    class_weight: str | None = None,
) -> tuple[float, list[dict[str, float]]]:
    """Pilih C di valid dengan PR-AUC; seri diputus oleh Brier terkecil."""
    results: list[dict[str, float]] = []
    for value in c_grid:
        pipeline = build_lr_pipeline(
            feature_columns,
            categorical_columns,
            c=value,
            class_weight=class_weight,
        )
        pipeline.fit(dataset.train.X[list(feature_columns)], dataset.train.y)
        proba = pipeline.predict_proba(dataset.valid.X[list(feature_columns)])[:, 1]
        results.append(
            {
                "c": float(value),
                "pr_auc": pr_auc(dataset.valid.y, proba),
                "brier": brier(dataset.valid.y, proba),
            }
        )

    best = min(results, key=lambda item: (-item["pr_auc"], item["brier"]))
    return best["c"], results


def coefficients_frame(pipeline: Pipeline) -> pd.DataFrame:
    """Koefisien dan odds ratio untuk setiap kolom hasil praproses."""
    names = pipeline.named_steps["pre"].get_feature_names_out()
    coefficients = pipeline.named_steps["clf"].coef_[0]
    frame = pd.DataFrame({"feature": list(names), "coefficient": coefficients})
    frame["odds_ratio"] = np.exp(frame["coefficient"])
    frame["abs_rank"] = frame["coefficient"].abs().rank(ascending=False, method="min").astype(int)
    return frame.sort_values("abs_rank").reset_index(drop=True)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def resolve_tracking_uri() -> str:
    """URI MLflow aktif; fallback ke folder ``mlruns`` lokal."""
    configured = (os.getenv("MLFLOW_TRACKING_URI") or "").strip()
    if configured:
        return configured
    return (Path.cwd() / "mlruns").resolve().as_uri()


# Nama lama dipertahankan supaya pemanggil internal tidak patah.
_resolve_tracking_uri = resolve_tracking_uri


def _latest_model_version(client: Any, registered_model_name: str) -> Any | None:
    versions = client.search_model_versions(f"name='{registered_model_name}'")
    if not versions:
        return None
    return max(versions, key=lambda item: int(item.version))


def set_model_alias(
    registered_model_name: str,
    alias: str,
    version: str | int,
    *,
    tracking_uri: str | None = None,
) -> None:
    """Set alias MLflow (mis. ``champion``) pada versi model tertentu."""
    import mlflow

    mlflow.set_tracking_uri(tracking_uri or resolve_tracking_uri())
    client = mlflow.tracking.MlflowClient()
    client.set_registered_model_alias(registered_model_name, alias, str(version))


def latest_model_version(
    registered_model_name: str,
    *,
    tracking_uri: str | None = None,
) -> str | None:
    """Versi terbaru sebuah registered model, atau ``None`` bila belum ada."""
    import mlflow

    mlflow.set_tracking_uri(tracking_uri or resolve_tracking_uri())
    client = mlflow.tracking.MlflowClient()
    latest = _latest_model_version(client, registered_model_name)
    return None if latest is None else str(latest.version)


def log_to_mlflow(
    settings: MLSettings,
    payload: dict[str, Any],
    artifacts: Sequence[Path],
    *,
    tracking_uri: str | None = None,
    model: Any | None = None,
    model_flavor: str | None = None,
    registered_model_name: str | None = None,
    parent_run_id: str | None = None,
    tags: Mapping[str, str] | None = None,
    input_example: pd.DataFrame | None = None,
    signature_input: pd.DataFrame | None = None,
    strict: bool = False,
) -> str | None:
    """Catat run ke MLflow; kembalikan run id atau ``None`` bila dilewati.

    ``parent_run_id`` membuat run ini nested di bawah pipeline run. Bila
    ``model`` diisi, model dicatat dengan flavor yang sesuai dan opsional
    didaftarkan ke model registry dengan alias ``candidate``.
    """
    try:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri or resolve_tracking_uri())
        mlflow.set_experiment(settings.experiment)
        run_name = payload.get("run_name")
        if not run_name:
            scope = payload.get("holdout_region") or payload["features"]
            run_name = f"{payload.get('model', 'lr')}-{payload['features']}-{scope}"
            if payload.get("c") is not None:
                run_name += f"-c{float(payload['c']):g}"
            if payload.get("drop_location_features"):
                run_name += "-noloc"
        with mlflow.start_run(
            run_name=run_name,
            nested=parent_run_id is not None,
            parent_run_id=parent_run_id,
        ) as run:
            params = {
                "model": payload["model"],
                "features": payload["features"],
                "threshold": payload["threshold"],
                "feature_count": len(payload["feature_columns"]),
                "grid_deg": payload["grid_deg"],
                "label_rule": payload["label_rule"],
                "label_horizon_days": payload["label_horizon_days"],
                "dataset_rows": (
                    payload["train_rows"] + payload["valid_rows"] + payload["test_rows"]
                ),
                "train_rows": payload["train_rows"],
                "valid_rows": payload["valid_rows"],
                "test_rows": payload["test_rows"],
            }
            for key in (
                "c",
                "class_weight",
                "vif",
                "num_leaves",
                "min_child_samples",
                "feature_fraction",
                "best_iteration",
                "feature_source",
                "feature_service",
                "feast_registry_hash",
                "feature_table_hash",
            ):
                if payload.get(key) is not None:
                    params[key] = str(payload[key])
            mlflow.log_params(params)
            for split in ("valid", "test"):
                metrics = payload.get(split)
                if not metrics:
                    continue
                for name, value in metrics.items():
                    if value is None:
                        continue
                    mlflow.log_metric(f"{split}_{name}", float(value))
            if payload.get("precision_at_100_test") is not None:
                mlflow.log_metric("precision_at_100_test", payload["precision_at_100_test"])
            run_tags = {
                "git_commit": payload.get("git_commit") or "unknown",
                "label_fingerprint": payload["label_fingerprint"],
                "manifest_hash": payload["manifest_hash"],
                "freeze_id": payload.get("freeze_id") or "unfrozen",
                "config_hash": payload.get("config_hash") or "none",
                "test_status": payload.get("test_status") or "evaluated",
                "feature_source": str(payload.get("feature_source") or "gold"),
                "feature_service": str(payload.get("feature_service") or ""),
                "feast_registry_hash": str(payload.get("feast_registry_hash") or ""),
                "feature_table_hash": str(payload.get("feature_table_hash") or ""),
            }
            if tags:
                run_tags.update({str(key): str(value) for key, value in tags.items()})
            mlflow.set_tags(run_tags)

            for artifact in artifacts:
                mlflow.log_artifact(str(artifact))

            if model is not None:
                signature = None
                signature_source = (
                    signature_input if signature_input is not None else input_example
                )
                if signature_source is not None:
                    try:
                        signature = mlflow.models.infer_signature(signature_source)
                    except Exception:  # noqa: BLE001 - signature opsional
                        signature = None
                if model_flavor == "sklearn":
                    model_info = mlflow.sklearn.log_model(
                        model,
                        artifact_path="model",
                        signature=signature,
                        input_example=input_example,
                        registered_model_name=registered_model_name,
                    )
                elif model_flavor == "lightgbm":
                    model_info = mlflow.lightgbm.log_model(
                        model,
                        artifact_path="model",
                        signature=signature,
                        input_example=input_example,
                        registered_model_name=registered_model_name,
                    )
                else:
                    raise TrainingError(f"model_flavor tidak dikenal: {model_flavor}")
                mlflow.set_tag("model_uri", model_info.model_uri)
                if registered_model_name:
                    client = mlflow.tracking.MlflowClient()
                    latest = _latest_model_version(client, registered_model_name)
                    if latest is not None:
                        client.set_registered_model_alias(
                            registered_model_name,
                            "candidate",
                            str(latest.version),
                        )
                        mlflow.set_tag("registered_model_name", registered_model_name)
                        mlflow.set_tag("registered_model_version", str(latest.version))
            return run.info.run_id
    except Exception as exc:  # noqa: BLE001 - MLflow opsional, jangan gagalkan training
        if strict:
            raise TrainingError(f"MLflow gagal: {exc}") from exc
        print(f"PERINGATAN: MLflow dilewati: {exc}", file=sys.stderr)
        return None


def filter_holdout_region(dataset: PreparedDataset, region: str) -> PreparedDataset:
    """Pindahkan satu wilayah ke test dan keluarkan dari train/valid."""
    validate_regions([region])

    def regions_of(data: SplitData) -> pd.Series:
        provinces = data.keys["province"].astype("string")
        mapped = provinces.map(PROVINCE_TO_REGION)
        if mapped.isna().any():
            unknown = sorted(provinces[mapped.isna()].unique().tolist())
            raise TrainingError(f"provinsi tidak dikenal: {unknown}")
        return mapped

    def subset(data: SplitData, mask: pd.Series) -> SplitData:
        array = mask.to_numpy(dtype=bool)
        return SplitData(
            X=data.X.loc[array].reset_index(drop=True),
            y=data.y.loc[array].reset_index(drop=True),
            keys=data.keys.loc[array].reset_index(drop=True),
        )

    train = subset(dataset.train, regions_of(dataset.train) != region)
    valid = subset(dataset.valid, regions_of(dataset.valid) != region)
    test = subset(dataset.test, regions_of(dataset.test) == region)

    for name, split in (("train", train), ("valid", valid), ("test", test)):
        if split.rows == 0:
            raise TrainingError(f"split {name} kosong setelah holdout {region}")

    holdout_cells = set(test.keys["cell_id"])
    shared = holdout_cells & (set(train.keys["cell_id"]) | set(valid.keys["cell_id"]))
    if shared:
        raise TrainingError(
            f"{len(shared)} cell_id muncul di holdout dan train/valid; periksa pemetaan wilayah"
        )

    return replace(dataset, train=train, valid=valid, test=test)


def load_registry(path: str | Path) -> dict[str, Any]:
    """Baca registry eksperimen; kembalikan struktur kosong bila belum ada."""
    registry_path = Path(path)
    if not registry_path.is_file():
        return {"families": {}, "runs": []}
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    payload.setdefault("families", {})
    payload.setdefault("runs", [])
    return payload


def save_registry(path: str | Path, registry: dict[str, Any]) -> None:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def assert_test_budget(
    registry_path: str | Path,
    family: str,
    test_window: Sequence[str],
    *,
    allow_seen: bool = False,
    holdout_region: str | None = None,
) -> None:
    """Tolak evaluasi test yang sudah pernah dilihat untuk keluarga ini."""
    registry = load_registry(registry_path)
    family_entry = registry["families"].get(family)
    if family_entry is None:
        raise TrainingError(f"keluarga eksperimen '{family}' belum ada di {registry_path}")
    registered = [str(item) for item in family_entry.get("test_window", [])]
    if registered != [str(item) for item in test_window]:
        raise TrainingError(
            f"jendela test {list(test_window)} tidak cocok dengan registry {registered}"
        )
    if holdout_region is not None:
        registered_region = family_entry.get("holdout_region")
        if registered_region != holdout_region:
            raise TrainingError(
                f"holdout {holdout_region} tidak cocok dengan registry {registered_region}"
            )
    looks = int(family_entry.get("test_looks", 0))
    if looks >= 1 and not allow_seen:
        raise TrainingError(
            f"test {registered} sudah dievaluasi {looks}x dan berstatus seen. "
            'Pakai --no-test untuk eksperimen, atau --allow-seen-test "<alasan>" '
            "hanya untuk laporan final."
        )


def record_run(
    registry_path: str | Path,
    family: str,
    entry: dict[str, Any],
) -> None:
    """Catat run ke registry dan tambah penghitung test bila dievaluasi."""
    registry = load_registry(registry_path)
    registry["runs"].append(entry)
    family_entry = registry["families"].setdefault(
        family,
        {"test_window": [], "test_looks": 0, "sealed": False},
    )
    if entry.get("test_status") == "evaluated":
        family_entry["test_looks"] = int(family_entry.get("test_looks", 0)) + 1
        family_entry["sealed"] = False
    save_registry(registry_path, registry)


def load_freeze_config(path: str | Path) -> dict[str, Any]:
    """Baca konfigurasi beku dan sertakan hash isi berkas."""
    config_path = Path(path)
    if not config_path.is_file():
        raise TrainingError(f"konfigurasi beku tidak ditemukan: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config["_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    config["_path"] = str(config_path)
    return config


def assert_freeze_matches(
    config: dict[str, Any],
    *,
    features: str,
    c: float,
    class_weight: str | None,
) -> None:
    """Pastikan run memakai parameter yang sama dengan konfigurasi beku."""
    expected_features = str(config.get("feature_group"))
    if expected_features != features:
        raise TrainingError(
            f"features {features} tidak cocok dengan konfigurasi beku {expected_features}"
        )
    expected_c = float(config.get("c"))
    if abs(expected_c - float(c)) > 1e-12:
        raise TrainingError(f"C {c} tidak cocok dengan konfigurasi beku {expected_c}")
    expected_weight = config.get("class_weight")
    if expected_weight != class_weight:
        raise TrainingError(
            f"class_weight {class_weight} tidak cocok dengan konfigurasi beku {expected_weight}"
        )


def run_training(
    settings: MLSettings,
    *,
    model: str = "lr",
    features: str = "t3",
    out_dir: str | Path | None = None,
    use_mlflow: bool = True,
    class_weight: str | None = None,
    c: float | None = None,
    c_grid: Sequence[float] = C_GRID,
    tracking_uri: str | None = None,
    vif: bool = False,
    test_policy: str = "sealed",
    test_reason: str | None = None,
    registry_path: str | Path | None = None,
    family: str = "lr-baseline",
    freeze_config: str | Path | None = None,
    holdout_region: str | None = None,
    drop_location_features: bool = False,
    feature_source: str = "gold",
    dataset: PreparedDataset | None = None,
    params: Mapping[str, Any] | None = None,
    register_model: bool = False,
    registered_model_name: str | None = None,
    mlflow_parent_run_id: str | None = None,
    mlflow_tags: Mapping[str, str] | None = None,
    mlflow_strict: bool = False,
) -> dict[str, Any]:
    """Latih satu konfigurasi dan tulis seluruh artefaknya."""
    if feature_source not in {"gold", "feast"}:
        raise TrainingError(f"feature_source tidak dikenal: {feature_source}")
    if model == "lgbm":
        return run_lgbm_training(
            settings,
            features=features,
            out_dir=out_dir,
            use_mlflow=use_mlflow,
            vif=vif,
            test_policy=test_policy,
            test_reason=test_reason,
            registry_path=registry_path,
            family=family,
            freeze_config=freeze_config,
            feature_source=feature_source,
            dataset=dataset,
            params=params,
            register_model=register_model,
            registered_model_name=registered_model_name,
            mlflow_parent_run_id=mlflow_parent_run_id,
            mlflow_tags=mlflow_tags,
            mlflow_strict=mlflow_strict,
            tracking_uri=tracking_uri,
        )
    if model != "lr":
        raise TrainingError(f"model belum didukung: {model}")
    if test_policy not in TEST_POLICIES:
        raise TrainingError(f"test_policy tidak dikenal: {test_policy}")
    if test_policy == "seen" and not (test_reason or "").strip():
        raise TrainingError("--allow-seen-test memerlukan alasan tertulis")

    include_history = features == "t3h"
    region_grouping = features == "t3r"
    if feature_source == "feast" and (include_history or region_grouping):
        raise TrainingError(
            "feature_source=feast belum mendukung grup t3h/t3r; pakai Gold atau perluas "
            "feature view Feast"
        )
    if dataset is None:
        dataset = prepare_from_settings(
            settings,
            include_history=include_history,
            region_grouping=region_grouping,
            feature_source=feature_source,
        )
    if include_history and not any(
        column in dataset.feature_columns for column in CELL_HISTORY_COLUMNS
    ):
        raise TrainingError("fitur riwayat tidak tersedia; periksa include_history")
    if region_grouping and "region" not in dataset.feature_columns:
        raise TrainingError("fitur region tidak tersedia")
    if holdout_region is not None:
        dataset = filter_holdout_region(dataset, holdout_region)
    selected = select_features(dataset.feature_columns, features)
    if drop_location_features:
        selected = [column for column in selected if column not in LOCATION_FEATURES]
        if not selected:
            raise TrainingError("semua fitur terbuang setelah ablasi lokasi")
    categorical = [column for column in dataset.categorical_columns if column in selected]
    numeric = [column for column in selected if column not in categorical]

    kept_numeric, dropped_vif = vif_filter(dataset.train.X, numeric)
    feature_columns = [
        column for column in selected if column in kept_numeric or column in categorical
    ]

    if c is None:
        best_c, c_results = tune_c(
            dataset,
            feature_columns,
            categorical,
            c_grid=c_grid,
            class_weight=class_weight,
        )
    else:
        best_c, c_results = float(c), []

    frozen: dict[str, Any] | None = None
    if freeze_config is not None:
        frozen = load_freeze_config(freeze_config)
        assert_freeze_matches(
            frozen,
            features=features,
            c=best_c,
            class_weight=class_weight,
        )

    pipeline = build_lr_pipeline(
        feature_columns,
        categorical,
        c=best_c,
        class_weight=class_weight,
    )
    started = time.perf_counter()
    pipeline.fit(dataset.train.X[feature_columns], dataset.train.y)
    fit_seconds = time.perf_counter() - started

    valid_proba = pipeline.predict_proba(dataset.valid.X[feature_columns])[:, 1]
    threshold = best_threshold(dataset.valid.y, valid_proba)
    precision_threshold = threshold_for_precision(dataset.valid.y, valid_proba)
    valid_metrics = binary_metrics(dataset.valid.y, valid_proba, threshold)

    test_window = (
        dataset.test.keys["date"].min().date().isoformat(),
        dataset.test.keys["date"].max().date().isoformat(),
    )

    if test_policy == "none":
        test_metrics: dict[str, float | int] | None = None
        per_day: float | None = None
        calibration: list[dict[str, float | int]] = []
    else:
        if registry_path is not None:
            assert_test_budget(
                registry_path,
                family,
                test_window,
                allow_seen=test_policy == "seen",
                holdout_region=holdout_region,
            )
        test_proba = pipeline.predict_proba(dataset.test.X[feature_columns])[:, 1]
        test_metrics = binary_metrics(dataset.test.y, test_proba, threshold)
        per_day = precision_at_k(
            dataset.test.y,
            test_proba,
            dataset.test.keys["date"],
            k=100,
        )
        calibration = calibration_table(dataset.test.y, test_proba)

    if out_dir is not None:
        output = Path(out_dir)
    else:
        output = settings.gold_root / "models" / f"lr-{features}"
    output.mkdir(parents=True, exist_ok=True)

    coefficients = coefficients_frame(pipeline)
    coefficients_path = output / "coefficients.csv"
    coefficients.to_csv(coefficients_path, index=False)

    valid_predictions = pd.DataFrame(
        {
            "cell_id": dataset.valid.keys["cell_id"].to_numpy(),
            "date": dataset.valid.keys["date"].to_numpy(),
            "label": dataset.valid.y.to_numpy(),
            "proba": valid_proba,
        }
    )
    valid_predictions_path = output / "valid_predictions.parquet"
    valid_predictions.to_parquet(valid_predictions_path, index=False)

    payload: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "model": model,
        "features": features,
        "run_name": f"lr-{features}-c{best_c:g}"
        + (f"-{holdout_region}" if holdout_region else "")
        + ("-noloc" if drop_location_features else ""),
        "c": best_c,
        "c_grid_results": c_results,
        "class_weight": class_weight,
        "freeze_id": frozen.get("id") if frozen else None,
        "config_hash": frozen.get("_sha256") if frozen else None,
        "test_status": "not_evaluated" if test_policy == "none" else "evaluated",
        "test_reason": test_reason,
        "test_window": list(test_window),
        "holdout_region": holdout_region,
        "drop_location_features": drop_location_features,
        "include_history": include_history,
        "region_grouping": region_grouping,
        "feature_source": feature_source,
        "feature_service": dataset.manifest.get("feature_service"),
        "feast_registry_hash": dataset.manifest.get("feast_registry_hash"),
        "feature_table_hash": dataset.manifest.get("feature_table_hash"),
        "label_rule": dataset.manifest["label_rule"],
        "label_horizon_days": dataset.manifest["label_horizon_days"],
        "label_fingerprint": dataset.manifest["label_fingerprint"],
        "grid_deg": dataset.manifest["grid_deg"],
        "manifest_hash": hashlib.sha256(dataset.manifest_json().encode("utf-8")).hexdigest(),
        "git_commit": _git_commit(),
        "threshold": threshold,
        "threshold_precision_target": precision_threshold,
        "feature_columns": feature_columns,
        "dropped_vif": dropped_vif,
        "protected_features": sorted(PROTECTED_FEATURES),
        "train_rows": dataset.train.rows,
        "valid_rows": dataset.valid.rows,
        "test_rows": dataset.test.rows,
        "positive_share": dataset.manifest["positive_share_complete"],
        "valid": valid_metrics,
        "test": test_metrics,
        "precision_at_100_test": per_day,
        "fit_seconds": fit_seconds,
    }

    pipeline_path = output / "pipeline.joblib"
    joblib.dump(pipeline, pipeline_path)
    (output / "metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "threshold.json").write_text(
        json.dumps(
            {
                "selected": threshold,
                "selected_metric": "f1_valid",
                "precision_target": TARGET_PRECISION,
                "threshold_for_precision_target": precision_threshold,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "calibration.json").write_text(
        json.dumps(calibration, indent=2) + "\n",
        encoding="utf-8",
    )

    artifacts = [
        pipeline_path,
        output / "metrics.json",
        coefficients_path,
        output / "threshold.json",
        output / "calibration.json",
        valid_predictions_path,
    ]

    mlflow_run_id: str | None = None
    if use_mlflow:
        mlflow_run_id = log_to_mlflow(
            settings,
            payload,
            artifacts,
            tracking_uri=tracking_uri,
            model=pipeline if register_model else None,
            model_flavor="sklearn" if register_model else None,
            registered_model_name=registered_model_name if register_model else None,
            parent_run_id=mlflow_parent_run_id,
            tags=mlflow_tags,
            input_example=(
                dataset.train.X[feature_columns].head(5) if register_model else None
            ),
            strict=mlflow_strict,
        )
        if mlflow_run_id:
            payload["mlflow_run_id"] = mlflow_run_id
            (output / "metrics.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    if registry_path is not None:
        record_run(
            registry_path,
            family,
            {
                "id": f"{family}-c{best_c:g}-{utc_now_iso()}",
                "freeze_id": payload.get("freeze_id"),
                "config_hash": payload.get("config_hash"),
                "features": features,
                "c": best_c,
                "class_weight": class_weight,
                "threshold": threshold,
                "valid_pr_auc": valid_metrics["pr_auc"],
                "test_pr_auc": (test_metrics or {}).get("pr_auc"),
                "test_status": payload["test_status"],
                "test_reason": test_reason,
                "holdout_region": holdout_region,
                "drop_location_features": drop_location_features,
                "feature_source": feature_source,
                "feature_service": payload.get("feature_service"),
                "mlflow_run_id": mlflow_run_id,
                "output": str(output),
            },
        )

    return {
        "payload": payload,
        "output": output,
        "valid_predictions": valid_predictions,
        "valid_keys": dataset.valid.keys,
        "valid_y": dataset.valid.y,
        "mlflow_run_id": mlflow_run_id,
    }


def run_lgbm_training(
    settings: MLSettings,
    *,
    features: str = "t3",
    out_dir: str | Path | None = None,
    use_mlflow: bool = True,
    vif: bool = False,
    test_policy: str = "sealed",
    test_reason: str | None = None,
    registry_path: str | Path | None = None,
    family: str = "lgbm-baseline",
    freeze_config: str | Path | None = None,
    grid: Sequence[Mapping[str, Any]] | None = None,
    feature_source: str = "gold",
    dataset: PreparedDataset | None = None,
    params: Mapping[str, Any] | None = None,
    register_model: bool = False,
    registered_model_name: str | None = None,
    mlflow_parent_run_id: str | None = None,
    mlflow_tags: Mapping[str, str] | None = None,
    mlflow_strict: bool = False,
    tracking_uri: str | None = None,
) -> dict[str, Any]:
    """Latih LightGBM dengan protokol yang sama seperti LR."""
    if feature_source not in {"gold", "feast"}:
        raise TrainingError(f"feature_source tidak dikenal: {feature_source}")
    if test_policy not in TEST_POLICIES:
        raise TrainingError(f"test_policy tidak dikenal: {test_policy}")
    if test_policy == "seen" and not (test_reason or "").strip():
        raise TrainingError("--allow-seen-test memerlukan alasan tertulis")

    if feature_source == "feast" and features in {"t3h", "t3r"}:
        raise TrainingError(
            "feature_source=feast belum mendukung grup t3h/t3r; pakai Gold atau perluas "
            "feature view Feast"
        )
    if dataset is None:
        dataset = prepare_from_settings(settings, feature_source=feature_source)
    selected = select_features(dataset.feature_columns, features)
    categorical = [column for column in dataset.categorical_columns if column in selected]
    numeric = [column for column in selected if column not in categorical]

    dropped_vif: list[dict[str, float | str]] = []
    if vif:
        kept_numeric, dropped_vif = vif_filter(dataset.train.X, numeric)
        feature_columns = [
            column for column in selected if column in kept_numeric or column in categorical
        ]
    else:
        feature_columns = list(selected)

    if params is None:
        best_params, tuning = tune_lgbm(
            dataset.train.X[feature_columns],
            dataset.train.y,
            dataset.valid.X[feature_columns],
            dataset.valid.y,
            categorical,
            grid=grid or DEFAULT_GRID,
        )
    else:
        best_params, tuning = dict(params), []

    frozen: dict[str, Any] | None = None
    if freeze_config is not None:
        frozen = load_freeze_config(freeze_config)
        assert_lgbm_freeze_matches(frozen, features=features, vif=vif, params=best_params)

    model = build_lgbm(**best_params)
    started = time.perf_counter()
    fit_lgbm(
        model,
        dataset.train.X[feature_columns],
        dataset.train.y,
        dataset.valid.X[feature_columns],
        dataset.valid.y,
        categorical_columns=categorical,
    )
    fit_seconds = time.perf_counter() - started

    valid_proba = model.predict_proba(
        prepare_categorical(dataset.valid.X[feature_columns], categorical)
    )[:, 1]
    threshold = best_threshold(dataset.valid.y, valid_proba)
    precision_threshold = threshold_for_precision(dataset.valid.y, valid_proba)
    valid_metrics = binary_metrics(dataset.valid.y, valid_proba, threshold)

    test_window = (
        dataset.test.keys["date"].min().date().isoformat(),
        dataset.test.keys["date"].max().date().isoformat(),
    )

    if test_policy == "none":
        test_metrics: dict[str, float | int] | None = None
        per_day: float | None = None
        calibration: list[dict[str, float | int]] = []
    else:
        if registry_path is not None:
            assert_test_budget(
                registry_path,
                family,
                test_window,
                allow_seen=test_policy == "seen",
            )
        test_proba = model.predict_proba(
            prepare_categorical(dataset.test.X[feature_columns], categorical)
        )[:, 1]
        test_metrics = binary_metrics(dataset.test.y, test_proba, threshold)
        per_day = precision_at_k(
            dataset.test.y,
            test_proba,
            dataset.test.keys["date"],
            k=100,
        )
        calibration = calibration_table(dataset.test.y, test_proba)

    if out_dir is not None:
        output = Path(out_dir)
    else:
        suffix = "-vif" if vif else ""
        output = settings.gold_root / "models" / f"lgbm-{features}{suffix}"
    output.mkdir(parents=True, exist_ok=True)

    model_path = output / "model.joblib"
    joblib.dump(model, model_path)
    importance = importance_frame(model)
    importance_path = output / "feature_importance.csv"
    importance.to_csv(importance_path, index=False)

    best_iteration = int(model.best_iteration_ or model.n_estimators)
    valid_predictions = pd.DataFrame(
        {
            "cell_id": dataset.valid.keys["cell_id"].to_numpy(),
            "date": dataset.valid.keys["date"].to_numpy(),
            "label": dataset.valid.y.to_numpy(),
            "proba": valid_proba,
        }
    )
    valid_predictions_path = output / "valid_predictions.parquet"
    valid_predictions.to_parquet(valid_predictions_path, index=False)

    payload: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "model": "lgbm",
        "features": features,
        "run_name": f"lgbm-{features}" + ("-vif" if vif else ""),
        "vif": vif,
        "feature_columns": feature_columns,
        "dropped_vif": dropped_vif,
        "num_leaves": best_params.get("num_leaves"),
        "min_child_samples": best_params.get("min_child_samples"),
        "feature_fraction": best_params.get("feature_fraction"),
        "best_iteration": best_iteration,
        "tuning": tuning,
        "feature_source": feature_source,
        "feature_service": dataset.manifest.get("feature_service"),
        "feast_registry_hash": dataset.manifest.get("feast_registry_hash"),
        "feature_table_hash": dataset.manifest.get("feature_table_hash"),
        "label_rule": dataset.manifest["label_rule"],
        "label_horizon_days": dataset.manifest["label_horizon_days"],
        "label_fingerprint": dataset.manifest["label_fingerprint"],
        "grid_deg": dataset.manifest["grid_deg"],
        "manifest_hash": hashlib.sha256(dataset.manifest_json().encode("utf-8")).hexdigest(),
        "git_commit": _git_commit(),
        "threshold": threshold,
        "threshold_precision_target": precision_threshold,
        "train_rows": dataset.train.rows,
        "valid_rows": dataset.valid.rows,
        "test_rows": dataset.test.rows,
        "positive_share": dataset.manifest["positive_share_complete"],
        "valid": valid_metrics,
        "test": test_metrics,
        "precision_at_100_test": per_day,
        "fit_seconds": fit_seconds,
        "freeze_id": frozen.get("id") if frozen else None,
        "config_hash": frozen.get("_sha256") if frozen else None,
        "test_status": "not_evaluated" if test_policy == "none" else "evaluated",
        "test_reason": test_reason,
        "test_window": list(test_window),
        "holdout_region": None,
        "include_history": False,
        "region_grouping": False,
    }

    (output / "metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "threshold.json").write_text(
        json.dumps(
            {
                "selected": threshold,
                "selected_metric": "f1_valid",
                "precision_target": TARGET_PRECISION,
                "threshold_for_precision_target": precision_threshold,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "calibration.json").write_text(
        json.dumps(calibration, indent=2) + "\n",
        encoding="utf-8",
    )

    artifacts = [
        model_path,
        output / "metrics.json",
        importance_path,
        output / "threshold.json",
        output / "calibration.json",
        valid_predictions_path,
    ]

    mlflow_run_id: str | None = None
    if use_mlflow:
        signature_input = None
        if register_model:
            signature_input = dataset.train.X[feature_columns].head(5).copy()
            for column in categorical:
                if column in signature_input.columns:
                    signature_input[column] = signature_input[column].astype(str)
        mlflow_run_id = log_to_mlflow(
            settings,
            payload,
            artifacts,
            tracking_uri=tracking_uri,
            model=model if register_model else None,
            model_flavor="lightgbm" if register_model else None,
            registered_model_name=registered_model_name if register_model else None,
            parent_run_id=mlflow_parent_run_id,
            tags=mlflow_tags,
            signature_input=signature_input,
            strict=mlflow_strict,
        )
        if mlflow_run_id:
            payload["mlflow_run_id"] = mlflow_run_id
            (output / "metrics.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    if registry_path is not None:
        record_run(
            registry_path,
            family,
            {
                "id": f"{family}-{utc_now_iso()}",
                "model": "lgbm",
                "vif": vif,
                "features": features,
                "params": best_params,
                "best_iteration": best_iteration,
                "threshold": threshold,
                "valid_pr_auc": valid_metrics["pr_auc"],
                "test_pr_auc": (test_metrics or {}).get("pr_auc"),
                "test_status": payload["test_status"],
                "test_reason": test_reason,
                "feature_source": feature_source,
                "feature_service": payload.get("feature_service"),
                "mlflow_run_id": mlflow_run_id,
                "output": str(output),
            },
        )

    return {
        "payload": payload,
        "output": output,
        "valid_predictions": valid_predictions,
        "valid_keys": dataset.valid.keys,
        "valid_y": dataset.valid.y,
        "mlflow_run_id": mlflow_run_id,
    }


def _parse_c_grid(raw: str | None) -> tuple[float, ...]:
    if raw is None:
        return C_GRID
    values = tuple(float(item) for item in raw.split(",") if item.strip())
    if not values:
        raise TrainingError("--c-grid kosong")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    settings = MLSettings.from_env()

    parser = argparse.ArgumentParser(description="Latih baseline LR dari Gold sel-hari")
    parser.add_argument("--model", choices=["lr", "lgbm"], default="lr")
    parser.add_argument("--features", choices=sorted(SELECTION_GROUPS), default="t3")
    parser.add_argument(
        "--feature-source",
        choices=["gold", "feast"],
        default="gold",
        help="gold = hitung fitur langsung; feast = ambil point-in-time dari Feast",
    )
    parser.add_argument("--out", default=None, help="folder artefak")
    parser.add_argument("--no-mlflow", action="store_true", help="jangan catat ke MLflow")
    parser.add_argument("--tracking-uri", default=None, help="override MLFLOW_TRACKING_URI")
    parser.add_argument(
        "--register-model",
        action="store_true",
        help="catat model ke MLflow Model Registry",
    )
    parser.add_argument(
        "--registered-model-name",
        default=None,
        help="nama registered model (default: ML_MODEL_NAME)",
    )
    parser.add_argument(
        "--mlflow-strict",
        action="store_true",
        help="gagalkan training kalau MLflow tidak bisa dihubungi",
    )
    parser.add_argument(
        "--class-weight",
        choices=["none", "balanced"],
        default="none",
        help="balanced hanya untuk uji sensitivitas",
    )
    parser.add_argument("--c", type=float, default=None, help="pakai C ini, lewati grid")
    parser.add_argument(
        "--vif",
        action="store_true",
        help="terapkan seleksi VIF sebelum training (untuk LightGBM)",
    )
    parser.add_argument("--c-grid", default=None, help="mis. 0.01,0.1,1,10")
    parser.add_argument(
        "--no-test",
        action="store_true",
        help="jangan hitung metrik test (default untuk eksperimen)",
    )
    parser.add_argument(
        "--allow-seen-test",
        default=None,
        metavar="ALASAN",
        help="evaluasi test yang sudah seen, wajib disertai alasan",
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="berkas registry eksperimen",
    )
    parser.add_argument("--family", default="lr-baseline", help="nama keluarga eksperimen")
    parser.add_argument(
        "--holdout-region",
        default=None,
        choices=list(ALL_REGIONS),
        help="spatial holdout: wilayah ini hanya muncul di test",
    )
    parser.add_argument(
        "--drop-location-features",
        action="store_true",
        help="ablasi: buang province, center_lat, center_lon, province_distance_km",
    )
    parser.add_argument(
        "--freeze-config",
        default=None,
        help="konfigurasi beku yang harus dicocokkan",
    )
    parser.add_argument("--gold-cell-root", default=str(settings.gold_cell_root))
    parser.add_argument("--test-days", type=int, default=settings.test_days)
    parser.add_argument("--valid-days", type=int, default=settings.valid_days)
    parser.add_argument("--purge-days", type=int, default=settings.purge_days)
    parser.add_argument("--min-train-rows", type=int, default=settings.min_train_rows)
    args = parser.parse_args(argv)

    configured = replace(
        settings,
        gold_cell_root=Path(args.gold_cell_root),
        test_days=args.test_days,
        valid_days=args.valid_days,
        purge_days=args.purge_days,
        min_train_rows=args.min_train_rows,
    )
    class_weight = None if args.class_weight == "none" else args.class_weight
    if args.no_test:
        test_policy = "none"
    elif args.allow_seen_test:
        test_policy = "seen"
    else:
        test_policy = "sealed"

    family = args.family
    if family == "lr-baseline":
        if args.model == "lgbm":
            family = "lgbm-baseline" if args.vif else "lgbm-baseline-all"
        elif args.holdout_region:
            family = f"lr-spatial-{region_slug(args.holdout_region)}"

    try:
        result = run_training(
            configured,
            model=args.model,
            features=args.features,
            out_dir=args.out,
            use_mlflow=not args.no_mlflow,
            class_weight=class_weight,
            c=args.c,
            vif=args.vif,
            c_grid=_parse_c_grid(args.c_grid),
            tracking_uri=args.tracking_uri,
            test_policy=test_policy,
            test_reason=args.allow_seen_test,
            registry_path=Path(args.registry),
            family=family,
            freeze_config=Path(args.freeze_config) if args.freeze_config else None,
            holdout_region=args.holdout_region,
            drop_location_features=args.drop_location_features,
            feature_source=args.feature_source,
            register_model=args.register_model,
            registered_model_name=(
                args.registered_model_name or settings.model_name
                if args.register_model
                else None
            ),
            mlflow_strict=args.mlflow_strict,
        )
    except (
        DatasetError,
        EvaluationError,
        TrainingError,
        LgbmError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = result["payload"]
    test = payload.get("test") or {}
    print(
        json.dumps(
            {
                "model": payload["model"],
                "features": payload["features"],
                "feature_source": payload.get("feature_source"),
                "feature_count": len(payload["feature_columns"]),
                "c": payload.get("c"),
                "vif": payload.get("vif"),
                "threshold": payload["threshold"],
                "test_status": payload["test_status"],
                "freeze_id": payload.get("freeze_id"),
                "holdout_region": payload.get("holdout_region"),
                "valid_pr_auc": payload["valid"]["pr_auc"],
                "test_pr_auc": test.get("pr_auc"),
                "test_roc_auc": test.get("roc_auc"),
                "test_f1": test.get("f1"),
                "precision_at_100_test": payload["precision_at_100_test"],
                "mlflow_run_id": payload.get("mlflow_run_id"),
                "output": str(result["output"]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
