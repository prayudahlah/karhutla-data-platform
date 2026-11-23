from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ml.regions import (
    ALL_REGIONS,
    CONFIRMATION_REGIONS,
    DEVELOPMENT_REGION,
    LOCATION_FEATURES,
    PROVINCE_TO_REGION,
    RegionError,
    region_of,
    region_slug,
    validate_regions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def _province_names() -> list[str]:
    with PROVINCES_CSV.open(encoding="utf-8", newline="") as handle:
        return [row["province"].strip() for row in csv.DictReader(handle)]


def test_mapping_covers_every_province() -> None:
    names = set(_province_names())
    assert set(PROVINCE_TO_REGION) == names
    assert len(PROVINCE_TO_REGION) == 38


def test_regions_are_consistent() -> None:
    assert len(ALL_REGIONS) == 7
    assert set(CONFIRMATION_REGIONS) <= set(ALL_REGIONS)
    assert DEVELOPMENT_REGION in ALL_REGIONS
    assert DEVELOPMENT_REGION not in CONFIRMATION_REGIONS


def test_region_helpers() -> None:
    assert region_of("Riau") == "Sumatra"
    assert region_of("Papua Selatan") == "Papua"
    assert region_slug("Bali_Nusa") == "bali_nusa"
    validate_regions(CONFIRMATION_REGIONS)

    with pytest.raises(RegionError, match="tidak dikenal"):
        region_of("Atlantis")

    with pytest.raises(RegionError, match="tidak dikenal"):
        validate_regions(["Atlantis"])


def test_location_features_are_documented() -> None:
    assert "province" in LOCATION_FEATURES
    assert "center_lat" in LOCATION_FEATURES
    assert "center_lon" in LOCATION_FEATURES
