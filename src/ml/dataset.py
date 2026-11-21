"""Dataset training dari Gold ``hotspot_cell_day``.

Satu baris = satu sel 0,25° pada satu hari. Label biner: 1 bila ada hotspot
``kuat`` atau ``sedang``, 0 bila hanya ``lemah``/``kandidat``. Modul ini hanya
menyiapkan matriks fitur, target, dan split temporal; agregasi sel dilakukan
dbt supaya training dan inference memakai angka yang sama.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds

from common.config import load_dotenv
from common.run import utc_now_iso
from ml.config import FEATURE_VERSION, GRID_DEG, LABEL_HORIZON_DAYS, POSITIVE_TIERS, MLSettings
from ml.features import FeatureSet, build_daily_context, cell_features
from ml.province import Province, load_provinces

CELL_REQUIRED_COLUMNS = (
    "cell_id",
    "date",
    "label",
    "label_complete",
    "n_hotspot",
    "center_lat",
    "center_lon",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


class DatasetError(RuntimeError):
    """Data Gold tidak cukup atau tidak sesuai kontrak ML."""


@dataclass(frozen=True)
class SplitDates:
    train: tuple[date, ...]
    valid: tuple[date, ...]
    test: tuple[date, ...]
    purge_days: int
    test_days: int
    valid_days: int


@dataclass(frozen=True)
class SplitData:
    X: pd.DataFrame
    y: pd.Series
    keys: pd.DataFrame

    @property
    def rows(self) -> int:
        return len(self.X)


@dataclass(frozen=True)
class PreparedDataset:
    train: SplitData
    valid: SplitData
    test: SplitData
    feature_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    categorical_levels: dict[str, list[str]]
    feature_version: str
    manifest: dict[str, Any]

    def manifest_json(self) -> str:
        return json.dumps(self.manifest, indent=2, ensure_ascii=False)


def read_parquet_dataset(root: str | Path) -> pd.DataFrame:
    """Baca semua parquet di bawah ``root`` dengan partisi hive.

    Kolom ``date`` diambil dari nama folder ``date=YYYY-MM-DD``. Sejak pyarrow
    versi baru, pembacaan tanpa ``partitioning="hive"`` membuang kolom tanggal
    fisik sehingga kontrak kolom Gold tidak terpenuhi.
    """
    path = Path(root)
    if not path.exists():
        raise DatasetError(f"Folder parquet tidak ditemukan: {path}")
    try:
        dataset = ds.dataset(path, format="parquet", partitioning="hive")
        table = dataset.to_table()
    except Exception as exc:  # noqa: BLE001 - pesan asli pyarrow tidak ramah
        raise DatasetError(f"Gagal membaca parquet di {path}: {exc}") from exc
    if table.num_rows == 0:
        raise DatasetError(f"Parquet kosong: {path}")
    return table.to_pandas()


def load_cell_day(root: str | Path, *, require_complete: bool = True) -> pd.DataFrame:
    """Muat tabel Gold dan buang baris yang jendela labelnya belum lengkap."""
    frame = read_parquet_dataset(root)
    missing = [column for column in CELL_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DatasetError(f"Tabel Gold kehilangan kolom: {', '.join(missing)}")

    frame = frame.drop_duplicates(subset=["cell_id", "date"], keep="last")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if frame["date"].isna().any():
        raise DatasetError("Tabel Gold memiliki date yang tidak valid")

    frame["label"] = pd.to_numeric(frame["label"], errors="coerce")
    invalid = frame["label"].isna() | ~frame["label"].isin([0, 1])
    if invalid.any():
        raise DatasetError(f"Ada {int(invalid.sum())} baris dengan label bukan 0/1")

    frame["label_complete"] = frame["label_complete"].astype("boolean").fillna(False).astype(bool)
    if require_complete:
        frame = frame.loc[frame["label_complete"]].copy()
        if frame.empty:
            raise DatasetError(
                "Tidak ada baris dengan jendela label lengkap; tambah cakupan burn scar"
            )

    frame["n_hotspot"] = pd.to_numeric(frame["n_hotspot"], errors="coerce")
    if (frame["n_hotspot"] < 1).any():
        raise DatasetError("Tabel Gold memiliki n_hotspot < 1")

    frame["label"] = frame["label"].astype("int8")
    return frame.reset_index(drop=True)


def assert_label_contract(frame: pd.DataFrame) -> None:
    """Gagal keras bila label tidak lagi sama dengan aturan kuat+sedang.

    Kontrak: ``label = 1`` bila dan hanya bila sel-hari memuat minimal satu
    hotspot ``kuat`` atau ``sedang``. ``lemah`` dan ``kandidat`` selalu 0.
    """
    if "audit_n_confirmed" not in frame.columns:
        return
    confirmed = pd.to_numeric(frame["audit_n_confirmed"], errors="coerce").fillna(0)
    label = pd.to_numeric(frame["label"], errors="coerce")
    bad_positive = (label == 1) & (confirmed < 1)
    bad_negative = (label == 0) & (confirmed > 0)
    if bad_positive.any() or bad_negative.any():
        raise DatasetError(
            "Label tidak sesuai kontrak kuat+sedang: "
            f"{int(bad_positive.sum())} positif tanpa konfirmasi, "
            f"{int(bad_negative.sum())} negatif padahal ada konfirmasi"
        )


def label_fingerprint(frame: pd.DataFrame) -> str:
    """Sidik jari label: SHA-256 dari (cell_id, date, label) terurut.

    Dipakai untuk membuktikan rebuild Gold tidak menggeser label.
    """
    keys = frame[["cell_id", "date", "label"]].astype(str)
    lines = sorted("|".join(row) for row in keys.itertuples(index=False))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def load_context(settings: MLSettings) -> pd.DataFrame:
    """Muat cuaca/AQ Silver jika tersedia; jika tidak, kembalikan tabel kosong."""
    weather = None
    air_quality = None
    if settings.weather_root.exists():
        try:
            weather = read_parquet_dataset(settings.weather_root)
        except DatasetError:
            weather = None
    if settings.air_quality_root.exists():
        try:
            air_quality = read_parquet_dataset(settings.air_quality_root)
        except DatasetError:
            air_quality = None
    return build_daily_context(weather, air_quality)


def _unique_dates(values: Iterable[Any]) -> list[date]:
    unique: set[date] = set()
    for value in values:
        if pd.isna(value):
            continue
        unique.add(pd.Timestamp(value).date())
    return sorted(unique)


def split_dates(
    dates: Iterable[Any],
    *,
    test_days: int = 5,
    valid_days: int = 5,
    purge_days: int = 3,
) -> SplitDates:
    """Split temporal dengan purge untuk mencegah kebocoran label scar.

    ``test_days`` dan ``valid_days`` dihitung dari jumlah tanggal unik yang ada
    di data. ``purge_days`` adalah jarak hari kalender yang dibuang di antara
    train-valid dan valid-test. Label memakai burn scar sampai 7 hari, jadi
    tanpa purge satu kejadian bisa muncul di dua sisi split.
    """
    if test_days < 1 or valid_days < 1:
        raise DatasetError("test_days dan valid_days harus >= 1")
    if purge_days < 0:
        raise DatasetError("purge_days tidak boleh negatif")

    unique = _unique_dates(dates)
    total = len(unique)
    test_start_index = total - test_days
    valid_end_index = test_start_index - purge_days - 1
    valid_start_index = valid_end_index - valid_days + 1
    train_end_index = valid_start_index - purge_days - 1

    if (
        total == 0
        or test_start_index < 0
        or valid_start_index < 0
        or valid_end_index < valid_start_index
        or train_end_index < 0
    ):
        raise DatasetError(
            f"Data hanya {total} tanggal; tidak cukup untuk test={test_days}, "
            f"valid={valid_days}, purge={purge_days}. "
            "Kurangi window atau tambah data historis."
        )

    train = tuple(unique[: train_end_index + 1])
    valid = tuple(unique[valid_start_index : valid_end_index + 1])
    test = tuple(unique[test_start_index:])

    if not train or not valid or not test:
        raise DatasetError("Salah satu split kosong setelah pembagian tanggal")
    if max(train) >= min(valid) or max(valid) >= min(test):
        raise DatasetError("Split temporal tumpang tindih; periksa parameter purge")

    return SplitDates(
        train=train,
        valid=valid,
        test=test,
        purge_days=purge_days,
        test_days=test_days,
        valid_days=valid_days,
    )


def _label_counts(target: pd.Series) -> dict[str, int]:
    counts = target.value_counts()
    return {
        "negative": int(counts.get(0, 0)),
        "positive": int(counts.get(1, 0)),
    }


def _split_summary(
    name: str,
    split: SplitDates,
    data: SplitData,
) -> dict[str, Any]:
    dates = getattr(split, name)
    counts = _label_counts(data.y)
    rows = data.rows
    return {
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "dates": len(dates),
        "rows": rows,
        "positive": counts["positive"],
        "negative": counts["negative"],
        "positive_share": (counts["positive"] / rows) if rows else 0.0,
    }


def _select_split(
    features: FeatureSet,
    target: pd.Series,
    dates: pd.Series,
    selected: tuple[date, ...],
) -> SplitData:
    mask = dates.isin(selected)
    return SplitData(
        X=features.features.loc[mask].reset_index(drop=True),
        y=target.loc[mask].reset_index(drop=True),
        keys=features.keys.loc[mask].reset_index(drop=True),
    )


def prepare_dataset(
    cells: pd.DataFrame,
    *,
    provinces: Sequence[Province] | None = None,
    context: pd.DataFrame | None = None,
    test_days: int = 5,
    valid_days: int = 5,
    purge_days: int = 3,
    include_context: bool = True,
    min_train_rows: int = 0,
    categorical_levels: Mapping[str, Sequence[str]] | None = None,
    require_complete: bool = True,
    include_history: bool = False,
    region_grouping: bool = False,
) -> PreparedDataset:
    """Siapkan fitur, target biner, dan split temporal dari tabel Gold."""
    frame = cells.copy().reset_index(drop=True)
    missing = [column for column in CELL_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DatasetError(f"Tabel Gold kehilangan kolom: {', '.join(missing)}")

    frame["label"] = pd.to_numeric(frame["label"], errors="coerce")
    invalid = frame["label"].isna() | ~frame["label"].isin([0, 1])
    if invalid.any():
        raise DatasetError(f"Ada {int(invalid.sum())} baris dengan label bukan 0/1")

    frame["label_complete"] = frame["label_complete"].astype("boolean").fillna(False).astype(bool)
    rows_total = len(frame)
    if require_complete:
        frame = frame.loc[frame["label_complete"]].reset_index(drop=True)
        if frame.empty:
            raise DatasetError("Tidak ada baris dengan jendela label lengkap")

    assert_label_contract(frame)

    feature_set = cell_features(
        frame,
        provinces=provinces,
        context=context,
        categorical_levels=categorical_levels,
        include_context=include_context,
        include_history=include_history,
        region_grouping=region_grouping,
    )

    target = frame["label"].astype("int8")
    dates = feature_set.keys["date"].dt.date
    split = split_dates(
        dates,
        test_days=test_days,
        valid_days=valid_days,
        purge_days=purge_days,
    )

    train = _select_split(feature_set, target, dates, split.train)
    valid = _select_split(feature_set, target, dates, split.valid)
    test = _select_split(feature_set, target, dates, split.test)

    if len(train.X) < min_train_rows:
        raise DatasetError(
            f"Train hanya {len(train.X)} baris; minimum {min_train_rows}. "
            "Tambah data atau turunkan ML_MIN_TRAIN_ROWS."
        )

    all_dates = sorted(set(dates.tolist()))
    rows_split = train.rows + valid.rows + test.rows
    per_day = (
        frame.assign(_day=dates).groupby("_day")["label"].mean().sort_index().to_dict()
    )

    manifest = {
        "generated_at": utc_now_iso(),
        "feature_version": FEATURE_VERSION,
        "label_rule": "+".join(POSITIVE_TIERS),
        "label_horizon_days": LABEL_HORIZON_DAYS,
        "label_fingerprint": label_fingerprint(frame),
        "grid_deg": GRID_DEG,
        "rows_total": rows_total,
        "rows_complete": len(frame),
        "rows_excluded_incomplete": rows_total - len(frame),
        "rows_split": rows_split,
        "rows_purged": len(frame) - rows_split,
        "positive_share_complete": float(target.mean()) if len(target) else 0.0,
        "date_range": {
            "start": all_dates[0].isoformat(),
            "end": all_dates[-1].isoformat(),
            "dates": len(all_dates),
        },
        "window": {
            "test_days": test_days,
            "valid_days": valid_days,
            "purge_days": purge_days,
        },
        "splits": {
            "train": _split_summary("train", split, train),
            "valid": _split_summary("valid", split, valid),
            "test": _split_summary("test", split, test),
        },
        "per_day_positive_share": {
            day.isoformat(): float(value) for day, value in per_day.items()
        },
        "feature_columns": list(feature_set.feature_columns),
        "categorical_levels": feature_set.categorical_levels,
    }

    return PreparedDataset(
        train=train,
        valid=valid,
        test=test,
        feature_columns=feature_set.feature_columns,
        categorical_columns=feature_set.categorical_columns,
        categorical_levels=feature_set.categorical_levels,
        feature_version=FEATURE_VERSION,
        manifest=manifest,
    )


def prepare_from_settings(
    settings: MLSettings,
    *,
    provinces: Sequence[Province] | None = None,
    include_context: bool = True,
    min_train_rows: int | None = None,
    require_complete: bool = True,
    include_history: bool = False,
    region_grouping: bool = False,
) -> PreparedDataset:
    """Muat Gold + konteks, lalu siapkan dataset sesuai setting environment."""
    if provinces is None and DEFAULT_PROVINCES_CSV.is_file():
        provinces = load_provinces(DEFAULT_PROVINCES_CSV)
    cells = load_cell_day(settings.gold_cell_root, require_complete=require_complete)
    context = load_context(settings) if include_context else None
    return prepare_dataset(
        cells,
        provinces=provinces,
        context=context,
        test_days=settings.test_days,
        valid_days=settings.valid_days,
        purge_days=settings.purge_days,
        include_context=include_context,
        min_train_rows=settings.min_train_rows if min_train_rows is None else min_train_rows,
        require_complete=require_complete,
        include_history=include_history,
        region_grouping=region_grouping,
    )


def save_manifest(dataset: PreparedDataset, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dataset.manifest_json() + "\n", encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    settings = MLSettings.from_env()

    parser = argparse.ArgumentParser(description="Siapkan dataset ML dari Gold sel-hari")
    parser.add_argument(
        "--gold-cell-root",
        default=str(settings.gold_cell_root),
        help="akar parquet Gold hotspot_cell_day (default: ML_GOLD_CELL_ROOT)",
    )
    parser.add_argument(
        "--out",
        default=str(settings.gold_root / "splits" / "split_manifest.json"),
        help="lokasi manifest split",
    )
    parser.add_argument(
        "--provinces",
        default=str(DEFAULT_PROVINCES_CSV),
        help="CSV referensi ibu kota provinsi",
    )
    parser.add_argument("--test-days", type=int, default=settings.test_days)
    parser.add_argument("--valid-days", type=int, default=settings.valid_days)
    parser.add_argument("--purge-days", type=int, default=settings.purge_days)
    parser.add_argument("--min-train-rows", type=int, default=settings.min_train_rows)
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="jangan join cuaca/AQ",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="ikutkan baris yang jendela labelnya belum lengkap",
    )
    args = parser.parse_args(argv)

    settings = replace(
        settings,
        gold_cell_root=Path(args.gold_cell_root),
        test_days=args.test_days,
        valid_days=args.valid_days,
        purge_days=args.purge_days,
        min_train_rows=args.min_train_rows,
    )

    try:
        provinces = load_provinces(Path(args.provinces))
        dataset = prepare_from_settings(
            settings,
            provinces=provinces,
            include_context=not args.no_context,
            require_complete=not args.include_incomplete,
        )
        output = save_manifest(dataset, Path(args.out))
    except (DatasetError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "train_rows": dataset.train.rows,
                "valid_rows": dataset.valid.rows,
                "test_rows": dataset.test.rows,
                "rows_purged": dataset.manifest["rows_purged"],
                "positive_share": dataset.manifest["positive_share_complete"],
                "features": len(dataset.feature_columns),
                "manifest": str(output),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
