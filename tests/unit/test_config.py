from __future__ import annotations

import pytest

from common.config import ConfigError, FirmsBronzeSettings, GarageSettings, Settings


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


def test_missing_garage_endpoint_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GARAGE_ENDPOINT", raising=False)

    with pytest.raises(ConfigError):
        GarageSettings.from_env()
