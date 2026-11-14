from __future__ import annotations

import pytest

from common.config import (
    BurnedAreaSettings,
    ConfigError,
    FirmsBronzeSettings,
    GarageSettings,
    OpenMeteoSettings,
    Settings,
)


def test_location_level_defaults_to_provinces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENMETEO_LOCATION_LEVEL", raising=False)

    settings = OpenMeteoSettings.from_env()

    assert settings.location_level == "province"
    assert settings.location_csv.name == "indonesia_provinces.csv"


def test_location_level_city_switches_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENMETEO_LOCATION_LEVEL", "city")

    settings = OpenMeteoSettings.from_env()

    assert settings.location_csv.name == "indonesia_cities.csv"


def test_unknown_location_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENMETEO_LOCATION_LEVEL", "kabupaten")

    with pytest.raises(ConfigError):
        OpenMeteoSettings.from_env()


def test_firms_bronze_prefix_defaults_to_bronze_firms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRONZE_PREFIX_FIRMS", raising=False)

    assert FirmsBronzeSettings.from_env().prefix == "bronze/firms"


def test_firms_bronze_prefix_strips_slashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRONZE_PREFIX_FIRMS", "/bronze/firms-v2/")

    assert FirmsBronzeSettings.from_env().prefix == "bronze/firms-v2"


def test_firms_and_open_meteo_prefixes_do_not_collide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARAGE_ENDPOINT", "http://127.0.0.1:3900")
    monkeypatch.setenv("GARAGE_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("GARAGE_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("BRONZE_PREFIX", raising=False)
    monkeypatch.delenv("BRONZE_PREFIX_FIRMS", raising=False)

    settings = Settings.from_env(env_file=None)

    assert settings.garage.prefix == "bronze/open_meteo"
    assert settings.firms_bronze.prefix == "bronze/firms"
    assert settings.garage.prefix != settings.firms_bronze.prefix


def test_burned_area_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BURNED_AREA_BBOX", "BRONZE_PREFIX_MCD64A1", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    settings = BurnedAreaSettings.from_env()

    assert settings.bbox == (95.0, -11.0, 141.0, 6.0)
    assert settings.bronze_prefix == "bronze/mcd64a1"
    assert settings.token == ""


def test_burned_area_bbox_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BURNED_AREA_BBOX", "100,-10,120,5")

    assert BurnedAreaSettings.from_env().bbox == (100.0, -10.0, 120.0, 5.0)


def test_burned_area_bbox_needs_four_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BURNED_AREA_BBOX", "100,-10,120")

    with pytest.raises(ConfigError):
        BurnedAreaSettings.from_env()


def test_burned_area_bbox_must_be_ordered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BURNED_AREA_BBOX", "120,-10,100,5")

    with pytest.raises(ConfigError):
        BurnedAreaSettings.from_env()


def test_missing_garage_endpoint_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GARAGE_ENDPOINT", raising=False)

    with pytest.raises(ConfigError):
        GarageSettings.from_env()
