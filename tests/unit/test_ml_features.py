from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

import pandas as pd  # noqa: E402

from ml.features import (  # noqa: E402
    CELL_BASE_COLUMNS,
    CELL_FEATURE_GROUPS,
    CELL_HISTORY_COLUMNS,
    CONTEXT_COLUMNS,
    LABEL_COLUMNS,
    add_detection_history,
    build_daily_context,
    build_features,
    cell_features,
)
from ml.province import load_provinces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def _provinces():
    return load_provinces(PROVINCES_CSV)


def _drop_labels(frame):
    return frame.drop(columns=[column for column in LABEL_COLUMNS if column in frame.columns])


def test_label_columns_never_become_features(hotspot_factory) -> None:
    frame = hotspot_factory(days=3)
    result = build_features(frame, provinces=_provinces(), include_context=False)
    assert set(LABEL_COLUMNS).isdisjoint(result.feature_columns)
    assert "tier" not in result.features.columns
    assert "burn_date" not in result.features.columns
    assert "gap_days" not in result.features.columns


def test_confidence_is_harmonized(hotspot_factory) -> None:
    frame = hotspot_factory(days=4, rows_per_day=1)
    frame.loc[0, ["confidence", "confidence_score", "satellite", "source", "instrument"]] = [
        "l",
        None,
        "N20",
        "VIIRS_NOAA20_NRT",
        "VIIRS",
    ]
    frame.loc[1, ["confidence", "confidence_score", "satellite", "source", "instrument"]] = [
        "n",
        None,
        "N21",
        "VIIRS_NOAA21_NRT",
        "VIIRS",
    ]
    frame.loc[2, ["confidence", "confidence_score", "satellite", "source", "instrument"]] = [
        "h",
        None,
        "N20",
        "VIIRS_NOAA20_NRT",
        "VIIRS",
    ]
    frame.loc[3, ["confidence", "confidence_score", "satellite", "source", "instrument"]] = [
        "85",
        85,
        "Terra",
        "MODIS_NRT",
        "MODIS",
    ]

    result = build_features(frame, provinces=_provinces(), include_context=False)
    assert result.features["confidence_norm"].tolist() == [30.0, 60.0, 90.0, 85.0]
    assert result.features["sensor_family"].astype(str).tolist() == [
        "VIIRS",
        "VIIRS",
        "VIIRS",
        "MODIS",
    ]


def test_time_features_from_acquisition_timestamp(hotspot_factory) -> None:
    frame = hotspot_factory(days=1, rows_per_day=1)
    result = build_features(frame, provinces=_provinces(), include_context=False)
    assert result.features.loc[0, "month"] == 1.0
    assert result.features.loc[0, "hour"] == 5.0
    assert result.features.loc[0, "day_of_year"] == 1.0
    assert pd.notna(result.features.loc[0, "doy_sin"])
    assert result.features.loc[0, "is_night"] == 0


def test_training_and_inference_have_identical_feature_columns(hotspot_factory) -> None:
    training = hotspot_factory(days=3)
    inference = _drop_labels(training)

    train_result = build_features(training, provinces=_provinces(), include_context=False)
    inference_result = build_features(
        inference,
        provinces=_provinces(),
        categorical_levels=train_result.categorical_levels,
        include_context=False,
    )
    assert train_result.feature_columns == inference_result.feature_columns


def test_unseen_category_is_not_added_during_inference(hotspot_factory) -> None:
    training = hotspot_factory(days=3)
    train_result = build_features(training, provinces=_provinces(), include_context=False)

    inference = _drop_labels(training).head(1).copy()
    inference["satellite"] = "N99"
    inference_result = build_features(
        inference,
        provinces=_provinces(),
        categorical_levels=train_result.categorical_levels,
        include_context=False,
    )
    assert (
        inference_result.categorical_levels["satellite"]
        == train_result.categorical_levels["satellite"]
    )
    assert pd.isna(inference_result.features.loc[0, "satellite"])


def test_daily_context_aggregates_weather_and_air_quality(
    hotspot_factory, weather_factory, air_quality_factory
) -> None:
    weather = weather_factory(days=3)
    air = air_quality_factory(days=3)
    context = build_daily_context(weather, air)

    assert set(CONTEXT_COLUMNS) <= set(context.columns)
    first = context.loc[context["date"] == pd.Timestamp("2026-01-01")].iloc[0]
    assert first["temp_max"] == pytest.approx(31.0)
    assert first["rh_min"] == pytest.approx(62.0)
    assert first["precip_sum"] == pytest.approx(0.5)
    assert first["pm25_mean"] == pytest.approx(19.0)
    assert first["aod_max"] == pytest.approx(0.38)


def test_precipitation_is_averaged_across_cities_not_summed() -> None:
    pd = pytest.importorskip("pandas")
    date = pd.Timestamp("2026-01-01")
    rows = []
    for city, precipitation in (("Pekanbaru", 0.5), ("Dumai", 1.5)):
        for hour in (0, 12):
            rows.append(
                {
                    "province": "Riau",
                    "city": city,
                    "date": date,
                    "ts_utc": date + pd.Timedelta(hours=hour),
                    "temperature_2m": 30.0,
                    "relative_humidity_2m": 70.0,
                    "precipitation": precipitation if hour == 12 else 0.0,
                    "wind_speed_10m": 5.0,
                    "soil_moisture_0_to_7cm": 0.2,
                    "vapour_pressure_deficit": 1.0,
                    "et0_fao_evapotranspiration": 0.1,
                }
            )
    context = build_daily_context(pd.DataFrame(rows), None)
    assert context.loc[0, "precip_sum"] == pytest.approx(1.0)


def test_empty_context_returns_expected_columns() -> None:
    context = build_daily_context(None, None)
    assert list(context.columns) == ["province", "date", *CONTEXT_COLUMNS]


def test_empty_context_still_keeps_feature_columns(hotspot_factory) -> None:
    result = build_features(
        hotspot_factory(days=1),
        provinces=_provinces(),
        context=build_daily_context(None, None),
        include_context=True,
    )
    assert set(CONTEXT_COLUMNS) <= set(result.feature_columns)
    assert result.features["temp_max"].isna().all()


def test_keys_include_province_and_distance(hotspot_factory) -> None:
    result = build_features(
        hotspot_factory(days=1, rows_per_day=1),
        provinces=_provinces(),
        include_context=False,
    )
    assert result.keys.loc[0, "province"] == "Riau"
    assert result.keys.loc[0, "province_city"] == "Pekanbaru"
    assert result.keys.loc[0, "province_distance_km"] == pytest.approx(0.0, abs=0.1)


# ------------------------------------------------------------- level sel


def test_cell_label_and_audit_columns_never_become_features(cell_factory) -> None:
    frame = cell_factory(days=3)
    result = cell_features(frame, provinces=_provinces(), include_context=False)

    assert set(LABEL_COLUMNS).isdisjoint(result.feature_columns)
    assert not any(column.startswith("audit_") for column in result.feature_columns)
    assert "label" not in result.features.columns
    assert "audit_n_candidate" not in result.features.columns


def test_cell_shares_are_derived_from_counts(cell_factory) -> None:
    frame = cell_factory(days=4, cells=2)
    result = cell_features(frame, provinces=_provinces(), include_context=False)

    expected_night = frame["n_night"] / frame["n_hotspot"]
    expected_viirs = frame["n_viirs"] / frame["n_hotspot"]
    assert result.features["night_share"].tolist() == pytest.approx(expected_night.tolist())
    assert result.features["viirs_share"].tolist() == pytest.approx(expected_viirs.tolist())


def test_cell_seasonality_follows_date(cell_factory) -> None:
    result = cell_features(cell_factory(days=1), provinces=_provinces(), include_context=False)
    angle = result.features["doy_sin"] ** 2 + result.features["doy_cos"] ** 2
    assert angle.tolist() == pytest.approx([1.0] * len(angle))


def test_cell_province_comes_from_center_coordinates(cell_factory) -> None:
    result = cell_features(
        cell_factory(days=1, cells=1),
        provinces=_provinces(),
        include_context=False,
    )
    assert result.keys.loc[0, "province"] == "Riau"
    assert result.keys.loc[0, "province_city"] == "Pekanbaru"
    assert result.keys.loc[0, "province_distance_km"] < 50


def test_cell_context_is_joined_by_province_and_date(
    cell_factory, weather_factory, air_quality_factory
) -> None:
    context = build_daily_context(
        weather_factory(days=3, start="2026-09-01"),
        air_quality_factory(days=3, start="2026-09-01"),
    )
    result = cell_features(
        cell_factory(days=3, cells=1),
        provinces=_provinces(),
        context=context,
        include_context=True,
    )
    assert set(CONTEXT_COLUMNS) <= set(result.feature_columns)
    assert result.features.loc[0, "temp_max"] == pytest.approx(31.0)
    assert result.features.loc[0, "pm25_mean"] == pytest.approx(19.0)
    assert result.features["temp_max"].notna().all()


def test_cell_training_and_inference_have_identical_columns(cell_factory) -> None:
    training = cell_factory(days=3)
    inference = training.drop(columns=["label", "audit_tier_max"]).copy()

    train_result = cell_features(training, provinces=_provinces(), include_context=False)
    inference_result = cell_features(
        inference,
        provinces=_provinces(),
        categorical_levels=train_result.categorical_levels,
        include_context=False,
    )
    assert train_result.feature_columns == inference_result.feature_columns


def test_cell_unknown_province_becomes_null(cell_factory) -> None:
    frame = cell_factory(days=1, cells=1)
    frame["province"] = "Atlantis"
    result = cell_features(
        frame,
        provinces=_provinces(),
        categorical_levels={"province": ["Riau"]},
        include_context=False,
    )
    assert pd.isna(result.features.loc[0, "province"])


def test_feature_groups_cover_every_feature() -> None:
    grouped = {column for columns in CELL_FEATURE_GROUPS.values() for column in columns}
    assert set(CELL_BASE_COLUMNS) <= grouped
    assert set(CONTEXT_COLUMNS) == set(CELL_FEATURE_GROUPS["context"])


def test_add_detection_history_uses_dense_dates() -> None:
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        {
            "cell_id": ["c", "c", "c", "c"],
            "date": pd.to_datetime(
                ["2026-09-01", "2026-09-04", "2026-09-10", "2026-09-11"]
            ),
            "n_hotspot": [2, 3, 4, 1],
        }
    )

    result = add_detection_history(frame).set_index("date")

    assert result.loc["2026-09-01", "has_history"] == 0
    assert result.loc["2026-09-04", "has_history"] == 1
    assert result.loc["2026-09-04", "n_hotspot_lag1"] == 0
    assert result.loc["2026-09-04", "n_hotspot_lag3"] == 2
    assert result.loc["2026-09-04", "n_hotspot_roll3"] == 3
    assert result.loc["2026-09-04", "days_since_previous_detection"] == 3
    assert result.loc["2026-09-10", "days_since_previous_detection"] == 6
    assert result.loc["2026-09-11", "days_since_previous_detection"] == 1
    assert result.loc["2026-09-10", "n_hotspot_lag1"] == 0


def test_history_columns_only_when_requested(cell_factory) -> None:
    frame = cell_factory(days=6, cells=1)

    without = cell_features(frame, provinces=_provinces(), include_context=False)
    with_history = cell_features(
        frame,
        provinces=_provinces(),
        include_context=False,
        include_history=True,
    )

    assert set(CELL_HISTORY_COLUMNS).isdisjoint(without.feature_columns)
    assert "n_hotspot_lag1" in with_history.feature_columns
    assert "has_history" in with_history.feature_columns
    assert with_history.features["has_history"].isin([0, 1]).all()


def test_region_grouping_replaces_province(cell_factory) -> None:
    result = cell_features(
        cell_factory(days=3, cells=2),
        provinces=_provinces(),
        include_context=False,
        region_grouping=True,
    )

    assert "region" in result.feature_columns
    assert "province" not in result.feature_columns
    assert set(result.features["region"].dropna().astype(str)) == {"Sumatra", "Jawa"}
    assert "region" in result.keys.columns
