"""Definisi Feast untuk fitur temporal hotspot.

Sumber data adalah dua tabel parquet Gold yang ditulis
``ml.feature_publish``:

- ``ml_feature_cell_day`` dengan entity ``cell`` (grain sel-hari)
- ``ml_feature_province_day`` dengan entity ``province`` (grain provinsi-hari)

Keduanya memakai ``event_timestamp`` yang sama sehingga
``get_historical_features`` melakukan join point-in-time yang benar. Label
tidak didaftarkan di feature view; label dibawa oleh ``entity_df``.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureService, FeatureView, Field, FileSource, ValueType
from feast.data_format import ParquetFormat
from feast.types import Float64

from ml.config import FEATURE_SERVICE
from ml.feature_publish import CELL_FEATURE_COLUMNS, PROVINCE_CONTEXT_COLUMNS
from ml.features import CELL_BASE_COLUMNS, CONTEXT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[1]
CELL_TABLE = REPO_ROOT / "data" / "gold" / "published" / "ml_feature_cell_day"
PROVINCE_TABLE = REPO_ROOT / "data" / "gold" / "published" / "ml_feature_province_day"

TTL = timedelta(days=3650)

cell = Entity(
    name="cell",
    join_keys=["cell_id"],
    value_type=ValueType.STRING,
    description="Sel grid 0,25 derajat, id berbentuk {cell_y}_{cell_x}.",
)
province = Entity(
    name="province",
    join_keys=["province"],
    value_type=ValueType.STRING,
    description="Provinsi terdekat dari pusat sel.",
)

cell_source = FileSource(
    name="gold_ml_feature_cell_day_source",
    path=CELL_TABLE.as_posix(),
    file_format=ParquetFormat(),
    timestamp_field="event_timestamp",
    created_timestamp_column="created_timestamp",
)
province_source = FileSource(
    name="gold_ml_feature_province_day_source",
    path=PROVINCE_TABLE.as_posix(),
    file_format=ParquetFormat(),
    timestamp_field="event_timestamp",
    created_timestamp_column="created_timestamp",
)

cell_day_features = FeatureView(
    name="hotspot_cell_day",
    entities=[cell],
    ttl=TTL,
    schema=[Field(name=column, dtype=Float64) for column in CELL_FEATURE_COLUMNS],
    source=cell_source,
    online=True,
    description=(
        "Agregat deteksi hotspot sel-hari: intensitas, kepadatan, lokasi, "
        "dan fitur waktu. Tidak memuat label."
    ),
    tags={"layer": "gold", "feature_version": "v2-cell"},
)

province_context_features = FeatureView(
    name="hotspot_province_context",
    entities=[province],
    ttl=TTL,
    schema=[Field(name=column, dtype=Float64) for column in PROVINCE_CONTEXT_COLUMNS],
    source=province_source,
    online=True,
    description=(
        "Konteks harian cuaca dan kualitas udara per provinsi, diagregasi "
        "dari Silver Open-Meteo."
    ),
    tags={"layer": "gold", "feature_version": "v2-cell"},
)

hotspot_training_v1 = FeatureService(
    name=FEATURE_SERVICE,
    features=[
        cell_day_features[list(CELL_FEATURE_COLUMNS)],
        province_context_features[list(PROVINCE_CONTEXT_COLUMNS)],
    ],
    description=(
        "39 fitur kandidat untuk model temporal hotspot. VIF di training "
        "memilih 29 fitur yang sama untuk LR dan LightGBM."
    ),
    tags={"purpose": "temporal-training"},
)


def get_objects():
    """Objek Feast yang didaftarkan lewat ``FeatureStore.apply``."""
    return [
        cell,
        province,
        cell_source,
        province_source,
        cell_day_features,
        province_context_features,
        hotspot_training_v1,
    ]


# Nama kolom yang diekspektasikan ikut di feature service; dipakai test agar
# daftar fitur tidak bergeser tanpa sengaja.
EXPECTED_FEATURE_COLUMNS: tuple[str, ...] = (*CELL_BASE_COLUMNS, *CONTEXT_COLUMNS)
