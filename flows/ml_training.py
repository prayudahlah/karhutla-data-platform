"""Flow Prefect: latih LR dan LightGBM temporal dari Feast.

Alur satu run:

1. bangun tabel fitur Gold (``ml.feature_publish``),
2. daftarkan definisi Feast dan materialize online store,
3. ambil dataset point-in-time dari Feast,
4. latih LR 29 fitur dan LightGBM 29 fitur,
5. bandingkan di valid dan tulis rekomendasi champion ke Gold.

Flow ini tidak mengevaluasi test. Jendela test 19-23 September 2026 sudah
``seen``; semua keputusan memakai valid.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import yaml
from prefect import flow, task

from common.config import load_dotenv
from common.run import utc_now_iso
from ml.compare import PredictionSet, compare_models
from ml.config import MLSettings
from ml.dataset import PreparedDataset, save_manifest
from ml.feast_dataset import prepare_from_feast
from ml.feast_store import (
    apply_feature_definitions,
    materialize_features,
)
from ml.feature_publish import publish_feature_tables
from ml.train import (
    latest_model_version,
    resolve_tracking_uri,
    run_training,
    set_model_alias,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_CONFIG = REPO_ROOT / "experiments" / "pipeline.yaml"


class PipelineError(RuntimeError):
    """Pipeline tidak bisa dijalankan dengan konfigurasi/data saat ini."""


def load_pipeline_config(path: str | Path = PIPELINE_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise PipelineError(f"Konfigurasi pipeline tidak ditemukan: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    for key in ("id", "models", "promotion"):
        if key not in payload:
            raise PipelineError(f"Konfigurasi pipeline kehilangan kunci: {key}")
    return payload


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _model_config(config: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    models = config.get("models") or {}
    if model_id not in models:
        raise PipelineError(f"Model config tidak dikenal: {model_id}")
    return dict(models[model_id])


def _write_dataset_parquet(dataset: PreparedDataset, path: Path) -> None:
    parts: list[pd.DataFrame] = []
    for name, split in (
        ("train", dataset.train),
        ("valid", dataset.valid),
        ("test", dataset.test),
    ):
        frame = split.X.copy()
        frame.insert(0, "split", name)
        frame.insert(1, "label", split.y.to_numpy())
        frame.insert(2, "cell_id", split.keys["cell_id"].to_numpy())
        frame.insert(3, "date", split.keys["date"].to_numpy())
        parts.append(frame)
    pd.concat(parts, ignore_index=True).to_parquet(path, index=False)


@task(name="publish-gold-features", retries=1, retry_delay_seconds=10)
def publish_gold_features(settings: MLSettings) -> dict[str, Any]:
    manifest = publish_feature_tables(settings, require_context=True)
    return {
        "cell_rows": manifest["cell_rows"],
        "province_rows": manifest["province_rows"],
        "dates": manifest["date_range"]["dates"],
        "feature_columns": manifest["feature_columns"],
        "cell_table_hash": manifest["cell_table_hash"],
        "cell_table_root": manifest["cell_table_root"],
        "manifest_path": manifest["manifest_path"],
    }


@task(name="feast-apply", retries=1, retry_delay_seconds=10)
def apply_feast(settings: MLSettings) -> dict[str, Any]:
    return apply_feature_definitions(settings)


@task(name="feast-materialize", retries=2, retry_delay_seconds=30)
def materialize_feast(settings: MLSettings) -> dict[str, Any]:
    return materialize_features(settings)


@task(name="build-feast-dataset", retries=1, retry_delay_seconds=10)
def build_training_dataset(settings: MLSettings, run_dir: Path) -> dict[str, Any]:
    dataset = prepare_from_feast(
        settings,
        min_train_rows=settings.min_train_rows,
    )
    dataset_dir = Path(run_dir) / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = dataset_dir / "dataset.joblib"
    joblib.dump(dataset, dataset_path)
    save_manifest(dataset, dataset_dir / "dataset_manifest.json")
    _write_dataset_parquet(dataset, dataset_dir / "dataset.parquet")
    return {
        "dataset_path": str(dataset_path),
        "manifest_path": str(dataset_dir / "dataset_manifest.json"),
        "rows": {
            "train": dataset.train.rows,
            "valid": dataset.valid.rows,
            "test": dataset.test.rows,
        },
        "feature_columns": list(dataset.feature_columns),
        "feature_source": dataset.manifest.get("feature_source"),
        "feature_service": dataset.manifest.get("feature_service"),
        "feast_registry_hash": dataset.manifest.get("feast_registry_hash"),
        "feature_table_hash": dataset.manifest.get("feature_table_hash"),
    }


@task(name="train-model", retries=0)
def train_model(
    settings: MLSettings,
    model_id: str,
    model_config: Mapping[str, Any],
    dataset_path: str | Path,
    run_dir: Path,
    parent_run_id: str | None,
    base_tags: Mapping[str, str],
    mlflow_required: bool,
) -> dict[str, Any]:
    dataset = joblib.load(dataset_path)
    output = Path(run_dir) / model_id
    config = dict(model_config)
    freeze = config.get("freeze_config")
    tags = {
        **dict(base_tags),
        "model_config": model_id,
        "model_family": str(config.get("model")),
    }
    result = run_training(
        settings,
        model=str(config.get("model")),
        features=str(config.get("features", "t3")),
        out_dir=output,
        use_mlflow=True,
        class_weight=config.get("class_weight"),
        c=config.get("c"),
        vif=bool(config.get("vif", False)),
        test_policy="none",
        registry_path=Path(run_dir) / "registry.yaml",
        family=model_id,
        freeze_config=(REPO_ROOT / str(freeze)) if freeze else None,
        feature_source="feast",
        dataset=dataset,
        params=config.get("params"),
        register_model=True,
        registered_model_name=config.get("registered_model_name"),
        mlflow_parent_run_id=parent_run_id,
        mlflow_tags=tags,
        mlflow_strict=mlflow_required,
    )
    payload = result["payload"]
    return {
        "model_id": model_id,
        "output": str(result["output"]),
        "payload": payload,
        "mlflow_run_id": result["mlflow_run_id"],
        "valid_predictions": str(Path(result["output"]) / "valid_predictions.parquet"),
        "feature_columns": payload.get("feature_columns"),
    }


def _assert_expected_features(
    model_results: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> None:
    expected = list(config.get("expected_features") or [])
    expected_count = int(config.get("expected_feature_count") or len(expected))
    for model_id, result in model_results.items():
        payload = result["payload"]
        actual = list(payload.get("feature_columns") or [])
        if len(actual) != expected_count:
            raise PipelineError(
                f"{model_id}: {len(actual)} fitur, seharusnya {expected_count}. "
                "Periksa VIF atau data fitur."
            )
        if expected and actual != expected:
            raise PipelineError(
                f"{model_id}: daftar fitur bergeser dari konfigurasi beku. "
                f"Selisih: {sorted(set(actual) ^ set(expected))}"
            )


def _log_parent_metrics(
    parent_run_id: str | None,
    comparison: Mapping[str, Any],
    model_results: Mapping[str, Mapping[str, Any]],
    comparison_path: Path,
) -> None:
    if not parent_run_id:
        return
    try:
        import mlflow

        mlflow.set_tracking_uri(resolve_tracking_uri())
        client = mlflow.tracking.MlflowClient()
        metrics = {
            "delta_valid_pr_auc": float(comparison["delta_valid"]["delta"]),
            "delta_valid_ci_low": float(comparison["delta_valid"]["ci_low"]),
            "delta_valid_ci_high": float(comparison["delta_valid"]["ci_high"]),
            "delta_valid_brier": float(comparison["delta_valid"]["brier_delta"]),
            "days_better": float(comparison["days_better"]),
        }
        for name, value in metrics.items():
            client.log_metric(parent_run_id, name, value)
        client.set_tag(parent_run_id, "recommended_model", comparison["recommended"])
        client.set_tag(parent_run_id, "comparison_decision", comparison["decision"])
        client.set_tag(parent_run_id, "test_status", "not_evaluated")
        for model_id, result in model_results.items():
            run_id = result.get("mlflow_run_id")
            if run_id:
                client.set_tag(parent_run_id, f"run_{model_id}", str(run_id))
            valid = (result.get("payload") or {}).get("valid") or {}
            if valid.get("pr_auc") is not None:
                client.log_metric(
                    parent_run_id,
                    f"valid_pr_auc_{model_id}",
                    float(valid["pr_auc"]),
                )
        client.log_artifact(parent_run_id, str(comparison_path))
    except Exception as exc:  # noqa: BLE001 - metrik parent tidak boleh menggagalkan run
        print(f"PERINGATAN: metrik parent MLflow dilewati: {exc}", file=sys.stderr)


@task(name="compare-and-finalize")
def compare_and_finalize(
    settings: MLSettings,
    run_dir: Path,
    pipeline_config: Mapping[str, Any],
    model_results: Mapping[str, Mapping[str, Any]],
    feature_manifest: Mapping[str, Any],
    feast_result: Mapping[str, Any],
    dataset_result: Mapping[str, Any],
    parent_run_id: str | None,
    promote: bool,
) -> dict[str, Any]:
    promotion = dict(pipeline_config.get("promotion") or {})
    baseline_id = str(promotion.get("baseline"))
    candidate_id = str(promotion.get("candidate"))
    if baseline_id not in model_results or candidate_id not in model_results:
        raise PipelineError(
            f"Model baseline/kandidat tidak ada di hasil: {baseline_id}, {candidate_id}"
        )

    predictions: dict[str, PredictionSet] = {}
    for model_id, result in model_results.items():
        path = Path(result["valid_predictions"])
        predictions[model_id] = PredictionSet(
            name=model_id,
            predictions=pd.read_parquet(path),
            payload=result["payload"],
        )

    comparison_path = Path(run_dir) / "comparison.json"
    comparison = compare_models(
        predictions[baseline_id],
        predictions[candidate_id],
        criteria=promotion,
        output=comparison_path,
    )
    _log_parent_metrics(parent_run_id, comparison, model_results, comparison_path)

    run_id = Path(run_dir).name
    model_payloads = {
        model_id: {
            "output": result["output"],
            "mlflow_run_id": result.get("mlflow_run_id"),
            "payload": result["payload"],
        }
        for model_id, result in model_results.items()
    }
    manifest = {
        "run_id": run_id,
        "generated_at": utc_now_iso(),
        "pipeline": pipeline_config.get("id"),
        "test_status": "not_evaluated",
        "test_policy": "none",
        "feature_source": "feast",
        "feature_service": pipeline_config.get("feature_service"),
        "feature_manifest": dict(feature_manifest),
        "feast": dict(feast_result),
        "dataset": dict(dataset_result),
        "models": model_payloads,
        "comparison": comparison,
        "mlflow": {"parent_run_id": parent_run_id},
    }
    manifest_path = Path(run_dir) / "pipeline_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lineage_path = settings.temporal_model_root / "runs.jsonl"
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    with lineage_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "generated_at": manifest["generated_at"],
                    "pipeline": manifest["pipeline"],
                    "feature_service": manifest["feature_service"],
                    "feature_table_hash": dataset_result.get("feature_table_hash"),
                    "models": {
                        model_id: {
                            "mlflow_run_id": result.get("mlflow_run_id"),
                            "valid_pr_auc": (result["payload"].get("valid") or {}).get(
                                "pr_auc"
                            ),
                        }
                        for model_id, result in model_results.items()
                    },
                    "comparison": comparison["decision"],
                    "recommended": comparison["recommended"],
                    "manifest": str(manifest_path),
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    champion = {
        "generated_at": utc_now_iso(),
        "run_id": run_id,
        "pipeline": pipeline_config.get("id"),
        "recommended": comparison["recommended"],
        "decision": comparison["decision"],
        "test_status": "not_evaluated",
        "promoted": False,
        "comparison": str(comparison_path),
        "manifest": str(manifest_path),
        "mlflow": {
            "parent_run_id": parent_run_id,
            "runs": {
                model_id: result.get("mlflow_run_id")
                for model_id, result in model_results.items()
            },
        },
    }

    if promote and comparison["decision"] == "accepted":
        recommended = str(comparison["recommended"])
        model_config = _model_config(pipeline_config, recommended)
        registered = model_config.get("registered_model_name")
        if registered:
            try:
                version = latest_model_version(registered)
                if version is not None:
                    set_model_alias(registered, "champion", version)
                    champion["promoted"] = True
                    champion["champion_alias"] = {
                        "registered_model_name": registered,
                        "alias": "champion",
                        "version": version,
                    }
            except Exception as exc:  # noqa: BLE001
                print(
                    f"PERINGATAN: alias champion gagal di-set: {exc}",
                    file=sys.stderr,
                )

    champion_path = settings.temporal_model_root / "champion.json"
    champion_path.parent.mkdir(parents=True, exist_ok=True)
    champion_path.write_text(
        json.dumps(champion, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (Path(run_dir) / "champion.json").write_text(
        json.dumps(champion, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "comparison": comparison,
        "manifest_path": str(manifest_path),
        "champion_path": str(champion_path),
        "champion": champion,
    }


def _start_parent_run(
    settings: MLSettings,
    run_id: str,
    *,
    required: bool,
) -> str | None:
    try:
        import mlflow

        mlflow.set_tracking_uri(resolve_tracking_uri())
        mlflow.set_experiment(settings.experiment)
        active = mlflow.start_run(
            run_name=f"temporal-pipeline-{run_id}",
            tags={
                "pipeline": "ml-temporal-training",
                "pipeline_run_id": run_id,
                "test_status": "not_evaluated",
                "feature_source": "feast",
            },
        )
        return active.info.run_id
    except Exception as exc:  # noqa: BLE001
        if required:
            raise PipelineError(f"MLflow wajib tetapi tidak bisa dihubungi: {exc}") from exc
        print(f"PERINGATAN: parent MLflow dilewati: {exc}", file=sys.stderr)
        return None


def _end_parent_run(parent_run_id: str | None, *, status: str = "FINISHED") -> None:
    if not parent_run_id:
        return
    try:
        import mlflow

        mlflow.set_tracking_uri(resolve_tracking_uri())
        mlflow.tracking.MlflowClient().set_terminated(
            parent_run_id,
            status=status,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"PERINGATAN: menutup parent MLflow gagal: {exc}", file=sys.stderr)
    finally:
        try:
            import mlflow

            mlflow.end_run()
        except Exception:  # noqa: BLE001
            pass


@flow(name="ml-temporal-training", log_prints=True)
def training_pipeline(
    run_id: str | None = None,
    model_configs: list[str] | None = None,
    promote: bool = False,
    mlflow_required: bool = False,
) -> dict[str, Any]:
    """Latih dua konfigurasi temporal dari Feast, manual lewat Prefect."""
    load_dotenv(".env")
    settings = MLSettings.from_env()
    pipeline_config = load_pipeline_config()
    selected = list(model_configs or pipeline_config["models"].keys())
    for model_id in selected:
        _model_config(pipeline_config, model_id)

    run_id = run_id or _new_run_id()
    run_dir = settings.temporal_model_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    feature_manifest = publish_gold_features(settings)
    feast_result = apply_feast(settings)
    materialized = materialize_feast(settings)
    dataset_result = build_training_dataset(settings, run_dir)

    parent_run_id = _start_parent_run(
        settings,
        run_id,
        required=mlflow_required,
    )
    base_tags = {
        "pipeline_run_id": run_id,
        "pipeline_config": str(pipeline_config.get("id")),
        "feature_source": "feast",
        "feature_service": str(pipeline_config.get("feature_service")),
        "test_status": "not_evaluated",
    }

    model_results: dict[str, dict[str, Any]] = {}
    try:
        for model_id in selected:
            model_results[model_id] = train_model(
                settings,
                model_id,
                _model_config(pipeline_config, model_id),
                dataset_result["dataset_path"],
                run_dir,
                parent_run_id,
                base_tags,
                mlflow_required,
            )
        _assert_expected_features(model_results, pipeline_config)
        final = compare_and_finalize(
            settings,
            run_dir,
            pipeline_config,
            model_results,
            feature_manifest,
            {**feast_result, **materialized},
            dataset_result,
            parent_run_id,
            promote,
        )
    except Exception:
        _end_parent_run(parent_run_id, status="FAILED")
        raise
    else:
        _end_parent_run(parent_run_id, status="FINISHED")

    summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "feature_rows": feature_manifest["cell_rows"],
        "feature_count": len(feature_manifest["feature_columns"]),
        "dataset_rows": dataset_result["rows"],
        "models": {
            model_id: {
                "valid_pr_auc": (result["payload"].get("valid") or {}).get("pr_auc"),
                "mlflow_run_id": result.get("mlflow_run_id"),
                "feature_count": len(result.get("feature_columns") or []),
            }
            for model_id, result in model_results.items()
        },
        "comparison": final["comparison"]["decision"],
        "recommended": final["comparison"]["recommended"],
        "promoted": final["champion"]["promoted"],
        "manifest": final["manifest_path"],
        "champion": final["champion_path"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    training_pipeline()
