"""Feature builder untuk klasifikasi risiko hotspot.

Satu fungsi dipakai bersama oleh training dan inference supaya urutan serta
nama kolom tidak pernah berbeda. Modul ini sengaja tidak menyentuh ``tier``,
``burn_date``, atau ``gap_days``: ketiganya adalah sumber label atau informasi
masa depan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ml.config import FEATURE_VERSION
from ml.province import (
    DEFAULT_PROVINCES_CSV,
    Province,
    assign_nearest_province,
    load_provinces,
)
from ml.regions import PROVINCE_TO_REGION

LABEL_COLUMNS = ("label", "tier", "burn_date", "gap_days")
KEY_COLUMNS = ("event_id", "date", "latitude", "longitude")
CATEGORICAL_COLUMNS = ("sensor_family", "satellite", "instrument", "source")

BASE_FEATURE_COLUMNS = (
    "latitude",
    "longitude",
    "frp",
    "frp_log1p",
    "brightness",
    "brightness_secondary",
    "brightness_diff",
    "scan",
    "track",
    "confidence_norm",
    "is_night",
    "sensor_family",
    "satellite",
    "instrument",
    "source",
    "month",
    "day_of_year",
    "doy_sin",
    "doy_cos",
    "hour",
)

WEATHER_CONTEXT_COLUMNS = (
    "temp_max",
    "temp_mean",
    "rh_min",
    "rh_mean",
    "precip_sum",
    "wind_max",
    "soil_moisture_mean",
    "vpd_max",
    "et0_sum",
)

AIR_QUALITY_CONTEXT_COLUMNS = (
    "pm25_mean",
    "pm25_max",
    "pm10_mean",
    "co_mean",
    "aod_mean",
    "aod_max",
)

CONTEXT_COLUMNS = WEATHER_CONTEXT_COLUMNS + AIR_QUALITY_CONTEXT_COLUMNS

CONTEXT_HISTORY_COLUMNS = ("precip_sum_roll3", "soil_moisture_mean_roll7")

CELL_HISTORY_DETECTION_COLUMNS = (
    "n_hotspot_lag1",
    "n_hotspot_lag2",
    "n_hotspot_lag3",
    "n_hotspot_roll3",
    "days_since_previous_detection",
    "has_history",
)

CELL_HISTORY_COLUMNS = (*CELL_HISTORY_DETECTION_COLUMNS, *CONTEXT_HISTORY_COLUMNS)


class FeatureError(ValueError):
    """Input tidak memiliki kolom yang dibutuhkan feature builder."""


@dataclass(frozen=True)
class FeatureSet:
    """Fitur siap model beserta kunci baris dan metadata kategori."""

    features: pd.DataFrame
    keys: pd.DataFrame
    feature_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    categorical_levels: dict[str, list[str]]
    context_columns: tuple[str, ...] = ()
    feature_version: str = FEATURE_VERSION


def _to_frame(data: Any) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    to_pandas = getattr(data, "to_pandas", None)
    if callable(to_pandas):
        return to_pandas()
    raise TypeError(
        "Data harus pandas.DataFrame atau objek dengan metode to_pandas(), "
        f"dapat {type(data).__name__}"
    )


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise FeatureError(f"Kolom wajib hilang: {', '.join(missing)}")


def _normalise_datetime(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_localize(None)
    return parsed.dt.normalize()


def _normalise_date(frame: pd.DataFrame) -> pd.DataFrame:
    frame["date"] = _normalise_datetime(frame["date"])
    if frame["date"].isna().any():
        raise FeatureError("Kolom date berisi nilai yang tidak bisa diurai")
    return frame


def _timestamp_from_acq(frame: pd.DataFrame) -> pd.Series:
    date = pd.to_datetime(frame["acq_date"], errors="coerce")
    raw_time = frame["acq_time"].astype("string").str.strip().str.replace(":", "", regex=False)
    raw_time = raw_time.str.zfill(4)
    hours = pd.to_numeric(raw_time.str.slice(0, 2), errors="coerce").fillna(0)
    minutes = pd.to_numeric(raw_time.str.slice(2, 4), errors="coerce").fillna(0)
    stamp = date + pd.to_timedelta(hours, unit="h") + pd.to_timedelta(minutes, unit="m")
    if getattr(stamp.dt, "tz", None) is None:
        return stamp.dt.tz_localize("UTC")
    return stamp.dt.tz_convert("UTC")


def _time_features(frame: pd.DataFrame) -> pd.DataFrame:
    if "acq_ts_utc" in frame.columns:
        stamp = pd.to_datetime(frame["acq_ts_utc"], errors="coerce", utc=True)
    else:
        stamp = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")

    if {"acq_date", "acq_time"} <= set(frame.columns) and stamp.isna().any():
        stamp = stamp.fillna(_timestamp_from_acq(frame))

    day_of_year_series = getattr(stamp.dt, "day_of_year", None)
    if day_of_year_series is None:  # pandas < 3
        day_of_year_series = stamp.dt.dayofyear
    day_of_year = day_of_year_series.astype("float64")
    angle = 2.0 * np.pi * (day_of_year - 1.0) / 365.25
    return pd.DataFrame(
        {
            "month": stamp.dt.month.astype("float64"),
            "day_of_year": day_of_year,
            "doy_sin": np.sin(angle),
            "doy_cos": np.cos(angle),
            "hour": stamp.dt.hour.astype("float64"),
        },
        index=frame.index,
    )


def _sensor_family(frame: pd.DataFrame) -> pd.Series:
    if "instrument" in frame.columns:
        instrument = frame["instrument"].astype("string")
    else:
        instrument = pd.Series(pd.NA, index=frame.index, dtype="string")
    if "source" in frame.columns:
        source = frame["source"].astype("string")
    else:
        source = pd.Series(pd.NA, index=frame.index, dtype="string")

    text = instrument.fillna("") + " " + source.fillna("")
    family = pd.Series("OTHER", index=frame.index, dtype="string")
    family = family.mask(text.str.contains("MODIS", case=False, na=False), "MODIS")
    family = family.mask(text.str.contains("VIIRS", case=False, na=False), "VIIRS")
    return family


def _confidence_norm(frame: pd.DataFrame) -> pd.Series:
    if "confidence_score" in frame.columns:
        score = pd.to_numeric(frame["confidence_score"], errors="coerce")
    else:
        score = pd.Series(np.nan, index=frame.index, dtype="float64")

    if "confidence" in frame.columns:
        raw = frame["confidence"].astype("string").str.strip().str.lower()
    else:
        raw = pd.Series(pd.NA, index=frame.index, dtype="string")

    mapped = pd.to_numeric(raw.map({"l": 30.0, "n": 60.0, "h": 90.0}), errors="coerce")
    numeric = pd.to_numeric(raw, errors="coerce")
    value = score.where(score.notna(), mapped)
    value = value.where(value.notna(), numeric)
    return value.astype("float64")


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def add_province(
    frame: pd.DataFrame,
    provinces: Sequence[Province] | None = None,
    *,
    lat_column: str = "latitude",
    lon_column: str = "longitude",
) -> pd.DataFrame:
    """Tambahkan ``province``, ``province_city``, dan jarak ke ibu kota."""
    result = frame.copy()
    if "province" in result.columns and result["province"].notna().all():
        result["province"] = result["province"].astype("string")
        if "province_distance_km" not in result.columns:
            result["province_distance_km"] = np.nan
        return result

    references = list(provinces) if provinces is not None else load_provinces(DEFAULT_PROVINCES_CSV)
    matches = assign_nearest_province(
        result[lat_column].to_numpy(dtype=float),
        result[lon_column].to_numpy(dtype=float),
        references,
    )
    result["province"] = pd.Series(matches.province, index=result.index, dtype="string")
    result["province_city"] = pd.Series(matches.city, index=result.index, dtype="string")
    result["province_distance_km"] = pd.Series(
        matches.distance_km, index=result.index, dtype="float64"
    )
    return result


def _aggregate(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    specs: Sequence[tuple[str, str, str]],
) -> pd.DataFrame:
    columns = [*group_columns, *[name for name, _, _ in specs]]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    present = [
        (name, column, operation) for name, column, operation in specs if column in frame.columns
    ]
    if not present:
        return pd.DataFrame(columns=columns)

    grouped = frame.groupby(list(group_columns), dropna=False).agg(
        **{
            name: pd.NamedAgg(column=column, aggfunc=operation)
            for name, column, operation in present
        }
    )
    for name, _, _ in specs:
        if name not in grouped.columns:
            grouped[name] = np.nan
    return grouped.reset_index()


WEATHER_DAILY_SPECS = (
    ("temp_max", "temperature_2m", "max"),
    ("temp_mean", "temperature_2m", "mean"),
    ("rh_min", "relative_humidity_2m", "min"),
    ("rh_mean", "relative_humidity_2m", "mean"),
    ("precip_sum", "precipitation", "sum"),
    ("wind_max", "wind_speed_10m", "max"),
    ("soil_moisture_mean", "soil_moisture_0_to_7cm", "mean"),
    ("vpd_max", "vapour_pressure_deficit", "max"),
    ("et0_sum", "et0_fao_evapotranspiration", "sum"),
)

WEATHER_PROVINCE_SPECS = (
    ("temp_max", "temp_max", "max"),
    ("temp_mean", "temp_mean", "mean"),
    ("rh_min", "rh_min", "min"),
    ("rh_mean", "rh_mean", "mean"),
    ("precip_sum", "precip_sum", "mean"),
    ("wind_max", "wind_max", "max"),
    ("soil_moisture_mean", "soil_moisture_mean", "mean"),
    ("vpd_max", "vpd_max", "max"),
    ("et0_sum", "et0_sum", "mean"),
)

AIR_QUALITY_DAILY_SPECS = (
    ("pm25_mean", "pm2_5", "mean"),
    ("pm25_max", "pm2_5", "max"),
    ("pm10_mean", "pm10", "mean"),
    ("co_mean", "carbon_monoxide", "mean"),
    ("aod_mean", "aerosol_optical_depth", "mean"),
    ("aod_max", "aerosol_optical_depth", "max"),
)

AIR_QUALITY_PROVINCE_SPECS = (
    ("pm25_mean", "pm25_mean", "mean"),
    ("pm25_max", "pm25_max", "max"),
    ("pm10_mean", "pm10_mean", "mean"),
    ("co_mean", "co_mean", "mean"),
    ("aod_mean", "aod_mean", "mean"),
    ("aod_max", "aod_max", "max"),
)


def _daily_province_context(
    frame: pd.DataFrame,
    daily_specs: Sequence[tuple[str, str, str]],
    province_specs: Sequence[tuple[str, str, str]],
) -> pd.DataFrame:
    """Agregat per provinsi; kota dihitung dulu agar hujan tidak dijumlah lintas kota."""
    if frame.empty:
        return _aggregate(frame, ("province", "date"), daily_specs)
    if "city" not in frame.columns:
        return _aggregate(frame, ("province", "date"), daily_specs)
    city_daily = _aggregate(frame, ("province", "city", "date"), daily_specs)
    return _aggregate(city_daily, ("province", "date"), province_specs)


def build_daily_context(
    weather: Any | None = None,
    air_quality: Any | None = None,
) -> pd.DataFrame:
    """Agregat harian cuaca dan AQ per provinsi, siap di-join ke hotspot."""
    weather_frame = _to_frame(weather) if weather is not None else pd.DataFrame()
    air_frame = _to_frame(air_quality) if air_quality is not None else pd.DataFrame()

    for name, frame in (("weather", weather_frame), ("air_quality", air_frame)):
        if frame.empty:
            continue
        _require_columns(frame, ("province", "date"))
        frame["province"] = frame["province"].astype("string")
        frame["date"] = _normalise_datetime(frame["date"])
        if frame["date"].isna().any():
            raise FeatureError(f"Kolom date pada {name} tidak valid")

    weather_agg = _daily_province_context(
        weather_frame,
        WEATHER_DAILY_SPECS,
        WEATHER_PROVINCE_SPECS,
    )
    air_agg = _daily_province_context(
        air_frame,
        AIR_QUALITY_DAILY_SPECS,
        AIR_QUALITY_PROVINCE_SPECS,
    )

    if weather_agg.empty and air_agg.empty:
        return pd.DataFrame(columns=["province", "date", *CONTEXT_COLUMNS])
    if weather_agg.empty:
        merged = air_agg
    elif air_agg.empty:
        merged = weather_agg
    else:
        merged = weather_agg.merge(
            air_agg,
            on=["province", "date"],
            how="outer",
            validate="one_to_one",
        )

    for column in CONTEXT_COLUMNS:
        if column not in merged.columns:
            merged[column] = np.nan
    return merged[["province", "date", *CONTEXT_COLUMNS]]


def add_context_history(context: pd.DataFrame) -> pd.DataFrame:
    """Tambah rolling 3 hari hujan dan rolling 7 hari kelembapan tanah."""
    frame = context.copy()
    frame["date"] = _normalise_datetime(frame["date"])
    frame = frame.sort_values(["province", "date"]).reset_index(drop=True)
    grouped = frame.groupby("province", sort=False)
    if "precip_sum" in frame.columns:
        frame["precip_sum_roll3"] = grouped["precip_sum"].transform(
            lambda values: values.rolling(3, min_periods=1).sum()
        )
    if "soil_moisture_mean" in frame.columns:
        frame["soil_moisture_mean_roll7"] = grouped["soil_moisture_mean"].transform(
            lambda values: values.rolling(7, min_periods=1).mean()
        )
    return frame


def add_detection_history(
    frame: pd.DataFrame,
    *,
    lags: Sequence[int] = (1, 2, 3),
    rolling_window: int = 3,
) -> pd.DataFrame:
    """Tambah fitur riwayat deteksi per sel pada grid tanggal padat.

    Hari tanpa deteksi dihitung 0, bukan dilewati. Fitur hanya melihat ke
    belakang, jadi tidak ada kebocoran masa depan. Baris yang belum punya
    riwayat (``has_history = 0``) dibiarkan kosong dan diimputasi pipeline.
    """
    working = frame[["cell_id", "date", "n_hotspot"]].copy()
    working["date"] = _normalise_datetime(working["date"])
    working["cell_id"] = working["cell_id"].astype(str)

    dates = pd.date_range(working["date"].min(), working["date"].max(), freq="D")
    cells = pd.Index(sorted(working["cell_id"].unique()), name="cell_id")
    grid = pd.MultiIndex.from_product([cells, dates], names=["cell_id", "date"]).to_frame(
        index=False
    )

    merged = grid.merge(working, on=["cell_id", "date"], how="left", validate="one_to_one")
    merged["n_hotspot"] = pd.to_numeric(merged["n_hotspot"], errors="coerce").fillna(0.0)
    merged = merged.sort_values(["cell_id", "date"]).reset_index(drop=True)
    grouped = merged.groupby("cell_id", sort=False)

    for lag in lags:
        merged[f"n_hotspot_lag{lag}"] = grouped["n_hotspot"].shift(lag)
    merged["n_hotspot_roll3"] = grouped["n_hotspot"].transform(
        lambda values: values.rolling(rolling_window, min_periods=1).sum()
    )

    first_date = grouped["date"].transform("min")
    merged["has_history"] = ((merged["date"] - first_date).dt.days >= max(lags)).astype("int8")

    detected = merged["n_hotspot"] > 0
    last_seen = merged["date"].where(detected)
    filled = last_seen.groupby(merged["cell_id"]).ffill()
    previous = filled.groupby(merged["cell_id"]).shift(1)
    days_since = (merged["date"] - previous).dt.days
    merged["days_since_previous_detection"] = days_since.fillna(30.0).where(
        merged["has_history"] == 1
    )

    history_columns = ["cell_id", "date", *CELL_HISTORY_DETECTION_COLUMNS]
    result = frame.merge(
        merged[history_columns],
        on=["cell_id", "date"],
        how="left",
        validate="one_to_one",
    )
    return result


def build_features(
    data: Any,
    *,
    provinces: Sequence[Province] | None = None,
    context: pd.DataFrame | None = None,
    categorical_levels: Mapping[str, Sequence[str]] | None = None,
    include_context: bool = True,
) -> FeatureSet:
    """Bangun fitur tanpa pernah menyertakan kolom label.

    Parameters
    ----------
    data:
        Tabel Silver ``hotspot_scar_label`` (training) atau ``firms_hotspot``
        (inference). Keduanya memakai kolom hotspot yang sama.
    provinces:
        Referensi 38 ibu kota. Dipakai bila kolom ``province`` belum ada.
    context:
        Hasil :func:`build_daily_context`. Di-join pada ``province`` dan ``date``.
    categorical_levels:
        Level kategori dari training. Wajib dipakai saat inference agar kategori
        yang tidak dikenal menjadi nilai kosong, bukan kategori baru.
    include_context:
        Set ``False`` untuk audit tanpa data cuaca/AQ.
    """
    frame = _to_frame(data).reset_index(drop=True)
    _require_columns(frame, KEY_COLUMNS)
    frame = _normalise_date(frame)

    if "province" not in frame.columns or frame["province"].isna().any():
        frame = add_province(frame, provinces)
    else:
        frame["province"] = frame["province"].astype("string")

    frame["sensor_family"] = _sensor_family(frame)
    frame["confidence_norm"] = _confidence_norm(frame)
    frame["frp"] = _numeric(frame, "frp")
    frame["frp_log1p"] = np.log1p(frame["frp"].clip(lower=0))
    frame["brightness"] = _numeric(frame, "brightness")
    frame["brightness_secondary"] = _numeric(frame, "brightness_secondary")
    frame["brightness_diff"] = frame["brightness"] - frame["brightness_secondary"]
    frame["scan"] = _numeric(frame, "scan")
    frame["track"] = _numeric(frame, "track")

    if "daynight" in frame.columns:
        frame["is_night"] = frame["daynight"].astype("string").str.upper().eq("N").astype("int8")
    else:
        frame["is_night"] = pd.Series(0, index=frame.index, dtype="int8")

    frame = frame.join(_time_features(frame))

    context_columns: list[str] = []
    if include_context and context is not None:
        _require_columns(context, ("province", "date"))
        context_frame = context.copy()
        context_frame["province"] = context_frame["province"].astype("string")
        context_frame["date"] = _normalise_datetime(context_frame["date"])
        available = [column for column in CONTEXT_COLUMNS if column in context_frame.columns]
        context_frame = context_frame[["province", "date", *available]]
        frame = frame.merge(
            context_frame,
            on=["province", "date"],
            how="left",
            validate="many_to_one",
        )
        context_columns = available

    feature_columns = list(BASE_FEATURE_COLUMNS) + context_columns
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = np.nan

    categorical_present = [column for column in CATEGORICAL_COLUMNS if column in feature_columns]
    levels: dict[str, list[str]] = {}
    for column in categorical_present:
        if categorical_levels is None:
            categories = sorted(frame[column].dropna().astype(str).unique().tolist())
        else:
            categories = [str(value) for value in categorical_levels.get(column, [])]
            if not categories:
                categories = sorted(frame[column].dropna().astype(str).unique().tolist())
        levels[column] = categories
        values = frame[column].astype("string")
        known = values.where(values.isin(categories), pd.NA)
        frame[column] = pd.Categorical(known, categories=categories)

    key_candidates = (
        *KEY_COLUMNS,
        "province",
        "province_city",
        "province_distance_km",
        "region",
    )
    key_columns = [column for column in key_candidates if column in frame.columns]
    keys = frame[key_columns].copy()
    features = frame[feature_columns].copy()

    leaked = sorted(set(LABEL_COLUMNS) & set(features.columns))
    if leaked:
        raise FeatureError(f"Kolom label tidak boleh menjadi fitur: {', '.join(leaked)}")

    return FeatureSet(
        features=features,
        keys=keys,
        feature_columns=tuple(feature_columns),
        categorical_columns=tuple(categorical_present),
        categorical_levels=levels,
        context_columns=tuple(context_columns),
        feature_version=FEATURE_VERSION,
    )


# --------------------------------------------------------------- level sel
#
# Fitur dihitung dari tabel Gold ``hotspot_cell_day``: satu baris per sel 0,25°
# per hari. Agregasi deteksi dilakukan di dbt supaya training dan inference
# memakai angka yang sama.

CELL_KEY_COLUMNS = ("cell_id", "date", "center_lat", "center_lon")

CELL_REQUIRED_COLUMNS = (
    *CELL_KEY_COLUMNS,
    "n_hotspot",
    "n_night",
    "n_viirs",
)

CELL_NUMERIC_COLUMNS = (
    "n_hotspot",
    "n_night",
    "n_satellite",
    "n_viirs",
    "frp_max",
    "frp_mean",
    "frp_p95",
    "brightness_max",
    "brightness_mean",
    "brightness_diff_max",
    "confidence_max",
    "confidence_mean",
    "scan_max",
    "track_max",
    "hour_of_max_frp",
    "hour_sin_mean",
    "hour_cos_mean",
)

CELL_INTENSITY_COLUMNS = (
    "frp_max",
    "frp_mean",
    "frp_p95",
    "brightness_max",
    "brightness_mean",
    "brightness_diff_max",
    "confidence_max",
    "confidence_mean",
    "scan_max",
    "track_max",
    "hour_of_max_frp",
)

CELL_DENSITY_COLUMNS = (
    "n_hotspot",
    "n_night",
    "night_share",
    "n_satellite",
    "viirs_share",
)

CELL_STATIC_COLUMNS = (
    "center_lat",
    "center_lon",
    "province",
    "province_distance_km",
    "doy_sin",
    "doy_cos",
    "hour_sin_mean",
    "hour_cos_mean",
)

AUDIT_PREFIX = "audit_"

CELL_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "intensity": CELL_INTENSITY_COLUMNS,
    "density": CELL_DENSITY_COLUMNS,
    "context": CONTEXT_COLUMNS,
    "static": CELL_STATIC_COLUMNS,
    "history": CELL_HISTORY_COLUMNS,
}

CELL_BASE_COLUMNS = (
    *CELL_INTENSITY_COLUMNS,
    *CELL_DENSITY_COLUMNS,
    *CELL_STATIC_COLUMNS,
)


def cell_features(
    data: Any,
    *,
    provinces: Sequence[Province] | None = None,
    context: pd.DataFrame | None = None,
    categorical_levels: Mapping[str, Sequence[str]] | None = None,
    include_context: bool = True,
    include_history: bool = False,
    region_grouping: bool = False,
) -> FeatureSet:
    """Bangun fitur level sel dari tabel Gold ``hotspot_cell_day``.

    Parameters
    ----------
    data:
        Tabel Gold: satu baris per ``cell_id`` dan ``date``.
    provinces:
        Referensi 38 ibu kota. Dipakai bila kolom ``province`` belum ada.
    context:
        Hasil :func:`build_daily_context`, di-join pada ``province`` dan ``date``.
    categorical_levels:
        Level kategori dari training. Wajib saat inference agar provinsi yang
        tidak dikenal menjadi nilai kosong, bukan kategori baru.
    include_context:
        ``False`` untuk audit atau ablasi tanpa cuaca/AQ.
    """
    frame = _to_frame(data).reset_index(drop=True)
    _require_columns(frame, CELL_REQUIRED_COLUMNS)
    frame = _normalise_date(frame)

    for column in CELL_NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    history_columns: list[str] = []
    if include_history:
        frame = add_detection_history(frame)
        history_columns = [
            column for column in CELL_HISTORY_DETECTION_COLUMNS if column in frame.columns
        ]

    hotspot = frame["n_hotspot"].astype("float64")
    denominator = hotspot.where(hotspot > 0)
    frame["night_share"] = frame["n_night"].astype("float64") / denominator
    frame["viirs_share"] = frame["n_viirs"].astype("float64") / denominator

    day_of_year_series = getattr(frame["date"].dt, "day_of_year", None)
    if day_of_year_series is None:  # pandas < 3
        day_of_year_series = frame["date"].dt.dayofyear
    day_of_year = day_of_year_series.astype("float64")
    angle = 2.0 * np.pi * (day_of_year - 1.0) / 365.25
    frame["doy_sin"] = np.sin(angle)
    frame["doy_cos"] = np.cos(angle)

    frame = add_province(
        frame,
        provinces,
        lat_column="center_lat",
        lon_column="center_lon",
    )
    if region_grouping:
        frame["region"] = frame["province"].astype("string").map(PROVINCE_TO_REGION)
        if frame["region"].isna().any():
            raise FeatureError("provinsi tidak bisa dipetakan ke wilayah")

    context_columns: list[str] = []
    if include_context and context is not None:
        _require_columns(context, ("province", "date"))
        context_frame = context.copy()
        context_frame["province"] = context_frame["province"].astype("string")
        context_frame["date"] = _normalise_datetime(context_frame["date"])
        if include_history:
            context_frame = add_context_history(context_frame)
        available = [
            column
            for column in (*CONTEXT_COLUMNS, *CONTEXT_HISTORY_COLUMNS)
            if column in context_frame.columns
        ]
        context_frame = context_frame[["province", "date", *available]]
        frame = frame.merge(
            context_frame,
            on=["province", "date"],
            how="left",
            validate="many_to_one",
        )
        context_columns = available

    base_columns = [
        column
        for column in CELL_BASE_COLUMNS
        if not (region_grouping and column == "province")
    ]
    if region_grouping:
        base_columns.append("region")

    feature_columns = [*base_columns, *context_columns, *history_columns]
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = np.nan

    categorical_candidates = ("region",) if region_grouping else ("province",)
    categorical_present = [
        column for column in categorical_candidates if column in feature_columns
    ]
    levels: dict[str, list[str]] = {}
    for column in categorical_present:
        if categorical_levels is None:
            categories = sorted(frame[column].dropna().astype(str).unique().tolist())
        else:
            categories = [str(value) for value in categorical_levels.get(column, [])]
            if not categories:
                categories = sorted(frame[column].dropna().astype(str).unique().tolist())
        levels[column] = categories
        values = frame[column].astype("string")
        known = values.where(values.isin(categories), pd.NA)
        frame[column] = pd.Categorical(known, categories=categories)

    key_candidates = (
        "cell_id",
        "date",
        "center_lat",
        "center_lon",
        "province",
        "province_city",
        "province_distance_km",
        "region",
    )
    key_columns = [column for column in key_candidates if column in frame.columns]
    features = frame[feature_columns].copy()

    leaked = [
        column
        for column in features.columns
        if column in LABEL_COLUMNS or column.startswith(AUDIT_PREFIX)
    ]
    if leaked:
        raise FeatureError(f"Kolom label/audit tidak boleh menjadi fitur: {', '.join(leaked)}")

    return FeatureSet(
        features=features,
        keys=frame[key_columns].copy(),
        feature_columns=tuple(feature_columns),
        categorical_columns=tuple(categorical_present),
        categorical_levels=levels,
        context_columns=tuple(context_columns),
        feature_version=FEATURE_VERSION,
    )
