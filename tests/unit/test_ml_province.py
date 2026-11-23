from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")

from ml.province import (  # noqa: E402
    assign_nearest_province,
    haversine_km,
    load_provinces,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def test_reference_has_38_unique_provinces() -> None:
    provinces = load_provinces(PROVINCES_CSV)
    assert len(provinces) == 38
    assert len({item.province for item in provinces}) == 38
    assert [item.number for item in provinces] == list(range(1, 39))


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        (0.5071, 101.4478, "Riau"),
        (-2.5916, 140.6690, "Papua"),
        (-8.4932, 140.4018, "Papua Selatan"),
        (-6.2088, 106.8456, "DKI Jakarta"),
    ],
)
def test_exact_capital_maps_to_its_province(
    latitude: float, longitude: float, expected: str
) -> None:
    provinces = load_provinces(PROVINCES_CSV)
    match = assign_nearest_province([latitude], [longitude], provinces)
    assert match.province[0] == expected
    assert match.distance_km[0] < 1.0


def test_invalid_coordinate_returns_none() -> None:
    provinces = load_provinces(PROVINCES_CSV)
    match = assign_nearest_province([float("nan")], [101.0], provinces)
    assert match.province[0] is None
    assert match.city[0] is None
    assert match.distance_km[0] != match.distance_km[0]  # NaN


def test_haversine_distance_is_plausible() -> None:
    distance = haversine_km(-6.2088, 106.8456, -6.9175, 107.6191)
    assert 100.0 < float(distance) < 140.0
