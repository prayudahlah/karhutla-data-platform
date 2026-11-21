"""Konfigurasi modul ML dari environment.

Modul ini tidak mengimpor pandas/lightgbm supaya bisa dipakai oleh CLI audit
tanpa memasang seluruh extra ``ml``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

FEATURE_VERSION = "v2-cell"
FEATURE_SERVICE = "hotspot_training_v1"
GRID_DEG = 0.25
LABEL_HORIZON_DAYS = 7
POSITIVE_TIERS: tuple[str, ...] = ("kuat", "sedang")
TIER_ORDER: tuple[str, ...] = ("kandidat", "lemah", "sedang", "kuat")


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} harus integer, dapat {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} harus angka, dapat {raw!r}") from exc


@dataclass(frozen=True)
class MLSettings:
    """Setting yang dipakai audit, dataset, training, dan inference."""

    silver_root: Path = Path("data/silver/published")
    gold_cell_root: Path = Path("data/gold/published/hotspot_cell_day")
    gold_root: Path = Path("data/gold")
    gold_prefix: str = "gold"
    feature_cell_root: Path = Path("data/gold/published/ml_feature_cell_day")
    feature_province_root: Path = Path("data/gold/published/ml_feature_province_day")
    temporal_model_root: Path = Path("data/gold/models/temporal")
    feast_repo: Path = Path("feature_repo")
    feast_registry: Path = Path("data/feast/registry.db")
    feast_online_store: Path = Path("data/feast/online_store.db")
    feature_service: str = FEATURE_SERVICE
    experiment: str = "karhutla-hotspot-risk"
    model_name: str = "karhutla-hotspot-cell-fire"
    binary_model_name: str = "karhutla-hotspot-cell-fire"
    grid_deg: float = GRID_DEG
    test_days: int = 5
    valid_days: int = 5
    purge_days: int = 3
    min_train_rows: int = 500
    random_state: int = 42
    feature_version: str = FEATURE_VERSION

    @classmethod
    def from_env(cls) -> MLSettings:
        silver_default = _get("SILVER_PUBLISH_ROOT", "data/silver/published")
        return cls(
            silver_root=Path(_get("ML_SILVER_ROOT", silver_default)),
            gold_cell_root=Path(
                _get("ML_GOLD_CELL_ROOT", "data/gold/published/hotspot_cell_day")
            ),
            gold_root=Path(_get("GOLD_ROOT", "data/gold")),
            gold_prefix=_get("GOLD_PREFIX", "gold").strip("/"),
            feature_cell_root=Path(
                _get("ML_FEATURE_CELL_ROOT", "data/gold/published/ml_feature_cell_day")
            ),
            feature_province_root=Path(
                _get(
                    "ML_FEATURE_PROVINCE_ROOT",
                    "data/gold/published/ml_feature_province_day",
                )
            ),
            temporal_model_root=Path(
                _get("ML_TEMPORAL_MODEL_ROOT", "data/gold/models/temporal")
            ),
            feast_repo=Path(_get("FEAST_REPO_PATH", "feature_repo")),
            feast_registry=Path(_get("FEAST_REGISTRY_PATH", "data/feast/registry.db")),
            feast_online_store=Path(
                _get("FEAST_ONLINE_STORE_PATH", "data/feast/online_store.db")
            ),
            feature_service=_get("ML_FEATURE_SERVICE", FEATURE_SERVICE),
            experiment=_get("ML_EXPERIMENT", "karhutla-hotspot-risk"),
            model_name=_get("ML_MODEL_NAME", "karhutla-hotspot-cell-fire"),
            binary_model_name=_get("ML_BINARY_MODEL_NAME", "karhutla-hotspot-cell-fire"),
            grid_deg=_get_float("ML_GRID_DEG", GRID_DEG),
            test_days=_get_int("ML_TEST_DAYS", 5),
            valid_days=_get_int("ML_VALID_DAYS", 5),
            purge_days=_get_int("ML_PURGE_DAYS", 3),
            min_train_rows=_get_int("ML_MIN_TRAIN_ROWS", 500),
            random_state=_get_int("ML_RANDOM_STATE", 42),
        )

    @property
    def hotspot_label_root(self) -> Path:
        return self.silver_root / "firms" / "hotspot_label"

    @property
    def hotspot_root(self) -> Path:
        return self.silver_root / "firms" / "hotspot"

    @property
    def weather_root(self) -> Path:
        return self.silver_root / "open_meteo" / "weather"

    @property
    def air_quality_root(self) -> Path:
        return self.silver_root / "open_meteo" / "air_quality"

    @property
    def audit_root(self) -> Path:
        return self.gold_root / "audit"

    @property
    def manifest_root(self) -> Path:
        return self.gold_root / "manifests"
