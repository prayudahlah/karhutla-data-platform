"""Bangun tabel fitur Gold yang dibaca Feast.

dbt tetap pemilik label dan agregat deteksi (``hotspot_cell_day``). Modul ini
menambahkan lapisan fitur siap-model di atasnya: provinsi, jarak ke ibu kota,
rasio malam/VIIRS, fitur waktu, dan konteks cuaca/AQ. Hasilnya dua tabel
parquet di Gold:

- ``ml_feature_cell_day``     : grain ``cell_id × date`` (23 fitur sel + kunci)
- ``ml_feature_province_day`` : grain ``province × date`` (15 fitur konteks)

Feast membaca tabel ini sebagai offline source dengan ``event_timestamp``.
Label hanya ikut di tabel sel untuk membentuk ``entity_df``; label tidak pernah
didaftarkan sebagai feature view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from common.config import load_dotenv
from common.run import utc_now_iso
from ml.config import FEATURE_VERSION, MLSettings
from ml.dataset import DatasetError, label_fingerprint, load_cell_day, load_context
from ml.features import CELL_BASE_COLUMNS, CONTEXT_COLUMNS, FeatureSet, cell_features
from ml.province import DEFAULT_PROVINCES_CSV, Province, load_provinces

CELL_FEATURE_COLUMNS: tuple[str, ...] = tuple(
    column for column in CELL_BASE_COLUMNS if column != "province"
)
PROVINCE_CONTEXT_COLUMNS: tuple[str, ...] = CONTEXT_COLUMNS
ALL_FEATURE_COLUMNS: tuple[str, ...] = (*CELL_BASE_COLUMNS, *CONTEXT_COLUMNS)

CELL_TABLE_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "province",
    "date",
    "event_timestamp",
    "created_timestamp",
    "feature_version",
    *CELL_FEATURE_COLUMNS,
    "label",
    "label_complete",
)

PROVINCE_TABLE_COLUMNS: tuple[str, ...] = (
    "province",
    "date",
    "event_timestamp",
    "created_timestamp",
    "feature_version",
    *PROVINCE_CONTEXT_COLUMNS,
)


class FeaturePublishError(RuntimeError):
    """Tabel fitur tidak bisa dibangun dari input yang tersedia."""


@dataclass(frozen=True)
class FeatureTables:
    """Dua tabel fitur siap tulis beserta manifest lineage."""

    cells: pd.DataFrame
    provinces: pd.DataFrame
    manifest: dict[str, Any]

    def written_manifest(self, manifest_path: Path) -> dict[str, Any]:
        payload = dict(self.manifest)
        payload["manifest_path"] = str(manifest_path)
        return payload


def _normalise_date(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_localize(None)
    return parsed.dt.normalize()


def _frame_hash(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    ordered = frame.sort_values(["cell_id", "date"]).reset_index(drop=True)
    hashed = pd.util.hash_pandas_object(ordered[list(columns)], index=False)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()


def _created_timestamp() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


def build_feature_frames(
    cells: pd.DataFrame,
    context: pd.DataFrame | None,
    *,
    provinces: Sequence[Province] | None = None,
    require_context: bool = True,
) -> FeatureTables:
    """Hitung dua tabel fitur tanpa menulis apa pun ke disk."""
    if cells.empty:
        raise FeaturePublishError("Tabel Gold sel kosong")
    if require_context and (context is None or context.empty):
        raise FeaturePublishError(
            "Konteks cuaca/AQ kosong; pipeline temporal membutuhkan 15 fitur konteks"
        )

    frame = cells.copy().reset_index(drop=True)
    frame["date"] = _normalise_date(frame["date"])
    if frame["date"].isna().any():
        raise FeaturePublishError("Kolom date Gold berisi nilai tidak valid")

    frame["label"] = pd.to_numeric(frame["label"], errors="coerce")
    frame["label_complete"] = (
        frame["label_complete"].astype("boolean").fillna(False).astype(bool)
    )
    invalid = frame["label_complete"] & ~frame["label"].isin([0, 1])
    if invalid.any():
        raise FeaturePublishError(
            f"Ada {int(invalid.sum())} baris lengkap dengan label bukan 0/1"
        )

    feature_set = cell_features(
        frame,
        provinces=provinces,
        context=context,
        include_context=context is not None and not context.empty,
    )
    _assert_feature_contract(feature_set, require_context=require_context)

    created = _created_timestamp()
    labels = frame[["cell_id", "date", "label", "label_complete"]].copy()
    labels["cell_id"] = labels["cell_id"].astype("string")
    labels["date"] = _normalise_date(labels["date"])

    keys = feature_set.keys.copy()
    keys["cell_id"] = keys["cell_id"].astype("string")
    keys["date"] = _normalise_date(keys["date"])

    cell_frame = keys[["cell_id", "date", "province"]].copy()
    cell_frame["province"] = cell_frame["province"].astype("string")
    for column in CELL_FEATURE_COLUMNS:
        cell_frame[column] = pd.to_numeric(
            feature_set.features[column], errors="coerce"
        ).astype("float64")
    cell_frame = cell_frame.merge(
        labels,
        on=["cell_id", "date"],
        how="left",
        validate="one_to_one",
    )
    cell_frame["label"] = cell_frame["label"].astype("Int64")
    cell_frame["event_timestamp"] = cell_frame["date"]
    cell_frame["created_timestamp"] = created
    cell_frame["feature_version"] = FEATURE_VERSION
    cell_frame = cell_frame[list(CELL_TABLE_COLUMNS)].reset_index(drop=True)

    if context is None or context.empty:
        province_frame = pd.DataFrame(columns=list(PROVINCE_TABLE_COLUMNS))
    else:
        province_frame = context.copy().reset_index(drop=True)
        province_frame["province"] = province_frame["province"].astype("string")
        province_frame["date"] = _normalise_date(province_frame["date"])
        for column in PROVINCE_CONTEXT_COLUMNS:
            province_frame[column] = pd.to_numeric(
                province_frame[column], errors="coerce"
            ).astype("float64")
        province_frame["event_timestamp"] = province_frame["date"]
        province_frame["created_timestamp"] = created
        province_frame["feature_version"] = FEATURE_VERSION
        province_frame = province_frame[list(PROVINCE_TABLE_COLUMNS)].reset_index(drop=True)

    complete = cell_frame.loc[cell_frame["label_complete"]].copy()
    if complete["label"].isna().any():
        raise FeaturePublishError("Baris label lengkap masih memiliki label kosong")

    dates = sorted(cell_frame["date"].dropna().unique())
    manifest: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "feature_version": FEATURE_VERSION,
        "cell_rows": len(cell_frame),
        "province_rows": len(province_frame),
        "rows_complete": len(complete),
        "positive_share_complete": (
            float(complete["label"].astype(float).mean()) if len(complete) else 0.0
        ),
        "date_range": {
            "start": pd.Timestamp(dates[0]).date().isoformat(),
            "end": pd.Timestamp(dates[-1]).date().isoformat(),
            "dates": len(dates),
        },
        "cell_feature_columns": list(CELL_FEATURE_COLUMNS),
        "province_context_feature_columns": (
            list(PROVINCE_CONTEXT_COLUMNS) if len(province_frame) else []
        ),
        "feature_columns": list(feature_set.feature_columns),
        "categorical_levels": feature_set.categorical_levels,
        "label_fingerprint": label_fingerprint(complete),
        "cell_table_hash": _frame_hash(
            cell_frame,
            ["cell_id", "date", *CELL_BASE_COLUMNS],
        ),
        "province_table_hash": (
            _frame_hash(
                province_frame.assign(cell_id=province_frame["province"]),
                ["cell_id", "date", *PROVINCE_CONTEXT_COLUMNS],
            )
            if len(province_frame)
            else None
        ),
    }
    combined = hashlib.sha256()
    for name in ("cell_table_hash", "province_table_hash"):
        combined.update(str(manifest[name] or "").encode("utf-8"))
    manifest["feature_table_hash"] = combined.hexdigest()
    return FeatureTables(cells=cell_frame, provinces=province_frame, manifest=manifest)


def _assert_feature_contract(feature_set: FeatureSet, *, require_context: bool) -> None:
    required = ALL_FEATURE_COLUMNS if require_context else CELL_BASE_COLUMNS
    missing = [column for column in required if column not in feature_set.features]
    if missing:
        raise FeaturePublishError(
            f"Feature builder tidak menghasilkan kolom: {', '.join(missing)}"
        )
    if require_context and not feature_set.context_columns:
        raise FeaturePublishError("Fitur konteks tidak ter-join; periksa cuaca/AQ Silver")
    forbidden = [
        column
        for column in feature_set.features.columns
        if column in {"label", "tier", "burn_date", "gap_days"}
        or column.startswith("audit_")
    ]
    if forbidden:
        raise FeaturePublishError(
            f"Kolom label/audit tidak boleh menjadi fitur: {', '.join(forbidden)}"
        )


def _write_partitioned(frame: pd.DataFrame, root: Path) -> Path:
    """Tulis satu file parquet per tanggal, menimpa isi lama."""
    if frame.empty:
        raise FeaturePublishError(f"Tabel fitur kosong: {root}")
    root = Path(root)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(frame, preserve_index=False)
    date_index = table.schema.get_field_index("date")
    table = table.set_column(date_index, "date", table["date"].cast(pa.date32()))
    ds.write_dataset(
        table,
        root,
        format="parquet",
        partitioning=ds.partitioning(pa.schema([("date", pa.date32())]), flavor="hive"),
        basename_template="data_{i}.parquet",
        existing_data_behavior="overwrite_or_ignore",
    )
    return root


def publish_feature_tables(
    settings: MLSettings,
    *,
    require_context: bool = True,
    provinces: Sequence[Province] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Bangun dan tulis kedua tabel fitur, lalu simpan manifest."""
    if provinces is None and DEFAULT_PROVINCES_CSV.is_file():
        provinces = load_provinces(DEFAULT_PROVINCES_CSV)
    cells = load_cell_day(settings.gold_cell_root, require_complete=False)
    context = load_context(settings)
    tables = build_feature_frames(
        cells,
        context,
        provinces=provinces,
        require_context=require_context,
    )

    cell_root = _write_partitioned(tables.cells, settings.feature_cell_root)
    province_root = (
        _write_partitioned(tables.provinces, settings.feature_province_root)
        if not tables.provinces.empty
        else None
    )

    destination = Path(manifest_path or settings.manifest_root / "ml_feature_tables.json")
    manifest = tables.written_manifest(destination)
    manifest["cell_table_root"] = str(cell_root)
    manifest["province_table_root"] = str(province_root) if province_root else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    settings = MLSettings.from_env()

    parser = argparse.ArgumentParser(
        description="Bangun tabel fitur Gold untuk Feast (sel-hari + konteks provinsi)"
    )
    parser.add_argument("--gold-cell-root", default=str(settings.gold_cell_root))
    parser.add_argument("--cell-root", default=str(settings.feature_cell_root))
    parser.add_argument("--province-root", default=str(settings.feature_province_root))
    parser.add_argument(
        "--manifest",
        default=str(settings.manifest_root / "ml_feature_tables.json"),
    )
    parser.add_argument(
        "--allow-missing-context",
        action="store_true",
        help="tetap tulis tabel sel walau cuaca/AQ kosong (tidak untuk pipeline 29 fitur)",
    )
    args = parser.parse_args(argv)

    configured = replace(
        MLSettings.from_env(),
        gold_cell_root=Path(args.gold_cell_root),
        feature_cell_root=Path(args.cell_root),
        feature_province_root=Path(args.province_root),
    )
    try:
        manifest = publish_feature_tables(
            configured,
            require_context=not args.allow_missing_context,
            manifest_path=Path(args.manifest),
        )
    except (DatasetError, FeaturePublishError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    manifest_path = Path(manifest["manifest_path"])
    print(
        json.dumps(
            {
                "cell_rows": manifest["cell_rows"],
                "province_rows": manifest["province_rows"],
                "dates": manifest["date_range"]["dates"],
                "feature_columns": len(manifest["feature_columns"]),
                "cell_table_hash": manifest["cell_table_hash"],
                "cell_table_root": manifest["cell_table_root"],
                "manifest": str(manifest_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
