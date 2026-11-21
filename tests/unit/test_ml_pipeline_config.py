from __future__ import annotations

from pathlib import Path

from flows.ml_training import load_pipeline_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_config_has_two_temporal_models() -> None:
    config = load_pipeline_config(REPO_ROOT / "experiments" / "pipeline.yaml")

    assert config["id"] == "temporal-pipeline-v1"
    assert set(config["models"]) == {"lr-temporal-29", "lgbm-temporal-29"}
    assert config["expected_feature_count"] == 29
    assert len(config["expected_features"]) == 29
    assert config["models"]["lr-temporal-29"]["c"] == 10.0
    assert config["models"]["lgbm-temporal-29"]["vif"] is True
    assert config["promotion"]["baseline"] == "lr-temporal-29"
    assert config["promotion"]["candidate"] == "lgbm-temporal-29"
    assert config["promotion"]["auto_promote"] is False
