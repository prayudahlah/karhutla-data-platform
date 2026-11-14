from __future__ import annotations

from pathlib import Path

import pytest

from ingest.openmeteo.locations import LocationError, load_cities, slugify

CSV_PATH = Path(__file__).resolve().parents[2] / "resources" / "indonesia_cities.csv"
PROVINCES_PATH = Path(__file__).resolve().parents[2] / "resources" / "indonesia_provinces.csv"


def test_province_reference_has_38_unique_entries() -> None:
    provinces = load_cities(PROVINCES_PATH)

    assert len(provinces) == 38
    assert len({province.province for province in provinces}) == 38
    assert len({province.slug for province in provinces}) == 38
    assert all(-11.5 <= province.latitude <= 6.5 for province in provinces)
    assert all(94.0 <= province.longitude <= 142.0 for province in provinces)


def test_provinces_are_numbered_one_to_38_in_order() -> None:
    provinces = load_cities(PROVINCES_PATH)

    assert [province.number for province in provinces] == list(range(1, 39))
    assert provinces[0].province == "Aceh"
    assert provinces[-1].province == "Papua Selatan"


def test_province_reference_covers_former_missing_provinces() -> None:
    names = {province.province for province in load_cities(PROVINCES_PATH)}

    assert "Sulawesi Barat" in names
    assert "Papua Barat" in names
    assert "Papua Selatan" in names
    assert "Papua Tengah" in names
    assert "Papua Pegunungan" in names


def test_reference_has_98_unique_indonesian_cities() -> None:
    cities = load_cities(CSV_PATH)

    assert len(cities) == 98
    assert len({city.slug for city in cities}) == 98
    assert all(-11.5 <= city.latitude <= 6.5 for city in cities)
    assert all(94.0 <= city.longitude <= 142.0 for city in cities)
    assert all(city.name.startswith("Kota ") for city in cities)


def test_filter_by_name_and_limit() -> None:
    cities = load_cities(CSV_PATH, names=["Kota Pekanbaru"])
    assert [city.name for city in cities] == ["Kota Pekanbaru"]

    limited = load_cities(CSV_PATH, limit=3)
    assert len(limited) == 3


def test_unknown_name_filter_raises() -> None:
    with pytest.raises(LocationError, match="No cities matched"):
        load_cities(CSV_PATH, names=["Kota Tidak Ada"])


def test_slugify_is_stable() -> None:
    assert slugify("Kota Administrasi Jakarta Pusat DKI Jakarta") == (
        "kota_administrasi_jakarta_pusat_dki_jakarta"
    )


def test_invalid_coordinate_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "cities.csv"
    csv_path.write_text(
        "city,province,latitude,longitude\nKota Test,Test,99.0,100.0\n",
        encoding="utf-8",
    )

    with pytest.raises(LocationError, match="Latitude out of Indonesian range"):
        load_cities(csv_path)
