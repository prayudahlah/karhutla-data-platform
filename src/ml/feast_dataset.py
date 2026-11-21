"""Dataset training dari Feast dengan point-in-time join.

Alur:

1. Baca tabel entity Gold ``ml_feature_cell_day`` (kunci + label).
2. Bagi tanggal dengan protokol temporal yang sama seperti jalur Gold.
3. Ambil 39 fitur dari feature service ``hotspot_training_v1`` memakai
   ``get_historical_features``.
4. Bentuk ``PreparedDataset`` yang identik kontraknya dengan jalur Gold.

Label tidak pernah diambil dari feature view; label ditempel dari entity frame
supaya tidak bisa bocor sebagai fitur.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ml.config import MLSettings
from ml.dataset import (
    DatasetError,
    PreparedDataset,
    assemble_prepared_dataset,
    read_parquet_dataset,
    split_dates,
)
from ml.feast_store import get_feature_store, registry_hash
from ml.feature_publish import CELL_FEATURE_COLUMNS
from ml.features import CELL_BASE_COLUMNS, CONTEXT_COLUMNS, FeatureSet

IDENTITY_COLUMNS = ("cell_id", "province", "event_timestamp", "label", "label_complete")
FEATURE_COLUMNS: tuple[str, ...] = (*CELL_BASE_COLUMNS, *CONTEXT_COLUMNS)
NUMERIC_FEATURE_COLUMNS: tuple[str, ...] = tuple(
    column for column in FEATURE_COLUMNS if column != "province"
)


def _normalise_timestamp(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(None)
    return parsed.dt.normalize()


def load_entity_frame(settings: MLSettings) -> pd.DataFrame:
    """Baca tabel sel Gold yang menjadi sumber entity dan label."""
    frame = read_parquet_dataset(settings.feature_cell_root)
    missing = [column for column in IDENTITY_COLUMNS if column not in frame.columns]
    if missing:
        raise DatasetError(
            f"Tabel fitur sel kehilangan kolom: {', '.join(missing)}. "
            "Jalankan `python -m ml.feature_publish`."
        )
    missing_features = [
        column for column in CELL_FEATURE_COLUMNS if column not in frame.columns
    ]
    if missing_features:
        raise DatasetError(
            "Tabel fitur sel tidak lengkap: " + ", ".join(missing_features)
        )

    frame = frame.drop_duplicates(subset=["cell_id", "event_timestamp"], keep="last")
    frame["cell_id"] = frame["cell_id"].astype("string")
    frame["province"] = frame["province"].astype("string")
    frame["event_timestamp"] = _normalise_timestamp(frame["event_timestamp"])
    if frame["event_timestamp"].isna().any():
        raise DatasetError("Tabel fitur sel memiliki event_timestamp tidak valid")
    frame["label"] = pd.to_numeric(frame["label"], errors="coerce")
    frame["label_complete"] = (
        frame["label_complete"].astype("boolean").fillna(False).astype(bool)
    )
    invalid = frame["label_complete"] & ~frame["label"].isin([0, 1])
    if invalid.any():
        raise DatasetError(
            f"Ada {int(invalid.sum())} baris lengkap dengan label bukan 0/1"
        )
    return frame.reset_index(drop=True)


def _load_feature_table_manifest(settings: MLSettings) -> dict[str, Any] | None:
    path = settings.manifest_root / "ml_feature_tables.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _feature_frame(retrieved: pd.DataFrame, entity_df: pd.DataFrame) -> pd.DataFrame:
    """Pastikan hasil Feast punya satu baris per entity dan kolom lengkap."""
    if "row_id" not in retrieved.columns:
        merged = retrieved.merge(
            entity_df[["cell_id", "event_timestamp", "row_id"]],
            on=["cell_id", "event_timestamp"],
            how="left",
            validate="many_to_one",
        )
    else:
        merged = retrieved

    if merged["row_id"].isna().any():
        raise DatasetError("Hasil Feast tidak bisa dipetakan kembali ke entity_df")
    if merged["row_id"].duplicated().any():
        raise DatasetError("Feast mengembalikan lebih dari satu baris per entity")
    if len(merged) != len(entity_df):
        raise DatasetError(
            f"Feast mengembalikan {len(merged)} baris untuk {len(entity_df)} entity"
        )

    missing = [column for column in FEATURE_COLUMNS if column not in merged.columns]
    if missing:
        raise DatasetError(
            "Feature service tidak mengembalikan kolom: " + ", ".join(missing)
        )

    # Urutan hasil Feast tidak dijamin; kembalikan ke urutan entity_df supaya
    # target dan keys tetap sejajar baris demi baris.
    merged = merged.sort_values("row_id").reset_index(drop=True)
    entity_sorted = entity_df.sort_values("row_id").reset_index(drop=True)

    features = pd.DataFrame(index=merged.index)
    features["province"] = entity_sorted["province"].astype("string")
    for column in NUMERIC_FEATURE_COLUMNS:
        features[column] = pd.to_numeric(merged[column], errors="coerce").astype("float64")
    return features[list(FEATURE_COLUMNS)]


def prepare_from_feast(
    settings: MLSettings,
    *,
    min_train_rows: int = 0,
    feature_store: Any | None = None,
) -> PreparedDataset:
    """Ambil dataset training dari Feast tanpa menyentuh label sebagai fitur."""
    entities = load_entity_frame(settings)
    complete = entities.loc[entities["label_complete"]].copy().reset_index(drop=True)
    if complete.empty:
        raise DatasetError(
            "Tidak ada baris dengan jendela label lengkap di tabel fitur Feast"
        )

    dates = complete["event_timestamp"].dt.date
    split = split_dates(
        dates,
        test_days=settings.test_days,
        valid_days=settings.valid_days,
        purge_days=settings.purge_days,
    )

    entity_df = pd.DataFrame(
        {
            "row_id": range(len(complete)),
            "cell_id": complete["cell_id"].astype(str),
            "province": complete["province"].astype(str),
            "event_timestamp": complete["event_timestamp"],
        }
    )

    store = feature_store or get_feature_store(settings)
    service = store.get_feature_service(settings.feature_service)
    retrieved = store.get_historical_features(
        entity_df=entity_df,
        features=service,
    ).to_df()

    features = _feature_frame(retrieved, entity_df)
    target = complete["label"].astype("int8").reset_index(drop=True)

    keys = pd.DataFrame(
        {
            "cell_id": complete["cell_id"].astype("string").to_numpy(),
            "date": _normalise_timestamp(complete["event_timestamp"]).to_numpy(),
            "center_lat": features["center_lat"].to_numpy(),
            "center_lon": features["center_lon"].to_numpy(),
            "province": features["province"].astype("string").to_numpy(),
            "province_distance_km": features["province_distance_km"].to_numpy(),
        }
    )

    levels = {
        "province": sorted(features["province"].dropna().astype(str).unique().tolist())
    }
    # Samakan dtype kategorikal dengan jalur Gold supaya LightGBM melihat set
    # kategori yang sama saat training dan saat input example disimpan.
    features["province"] = pd.Categorical(
        features["province"].astype(str),
        categories=levels["province"],
    )
    feature_set = FeatureSet(
        features=features,
        keys=keys,
        feature_columns=FEATURE_COLUMNS,
        categorical_columns=("province",),
        categorical_levels=levels,
        context_columns=CONTEXT_COLUMNS,
        feature_version=settings.feature_version,
    )

    label_frame = pd.DataFrame(
        {
            "cell_id": complete["cell_id"].astype("string"),
            "date": _normalise_timestamp(complete["event_timestamp"]),
            "label": target,
        }
    )

    table_manifest = _load_feature_table_manifest(settings)
    table_hash = (table_manifest or {}).get("feature_table_hash") or (
        table_manifest or {}
    ).get("cell_table_hash")
    extra_manifest = {
        "feature_source": "feast",
        "feature_service": settings.feature_service,
        "feast_registry": str(settings.feast_registry),
        "feast_registry_hash": registry_hash(settings),
        "feature_table_manifest": str(
            settings.manifest_root / "ml_feature_tables.json"
        ),
        "feature_table_hash": table_hash,
        "feature_table_root": str(settings.feature_cell_root),
        "feature_table_content_hash": (
            _sha256_json(table_manifest) if table_manifest is not None else None
        ),
    }

    return assemble_prepared_dataset(
        feature_set=feature_set,
        target=target,
        dates=keys["date"].dt.date,
        split=split,
        label_frame=label_frame,
        rows_total=len(entities),
        min_train_rows=min_train_rows,
        extra_manifest=extra_manifest,
    )


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dataset_manifest_path(output: str | Path) -> Path:
    return Path(output) / "dataset_manifest.json"
