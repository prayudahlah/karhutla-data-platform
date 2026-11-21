"""Pemetaan hotspot ke provinsi lewat ibu kota terdekat.

Repo belum memiliki batas administrasi provinsi (GeoJSON/shapefile). Satu-satunya
referensi spasial resmi yang ada adalah ``resources/indonesia_provinces.csv``:
satu titik ibu kota untuk masing-masing 38 provinsi. Modul ini memakai titik itu
sebagai pusat wilayah, konsisten dengan cara Open-Meteo mengambil cuaca.

Keterbatasan: hotspot di pedalaman provinsi besar bisa lebih dekat ke ibu kota
provinsi lain. Karena itu jarak ikut dikembalikan supaya audit bisa melaporkan
berapa persen hotspot yang jauh dari pusat wilayahnya.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"
EARTH_RADIUS_KM = 6371.0088
DEFAULT_CHUNK_SIZE = 100_000


class ProvinceError(ValueError):
    """Data referensi provinsi tidak lengkap atau tidak valid."""


@dataclass(frozen=True)
class Province:
    number: int
    city: str
    province: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ProvinceMatch:
    """Hasil pemetaan; panjang array sama dengan jumlah hotspot."""

    province: np.ndarray
    city: np.ndarray
    distance_km: np.ndarray


def load_provinces(path: Path = DEFAULT_PROVINCES_CSV) -> list[Province]:
    """Baca daftar 38 ibu kota provinsi dari CSV referensi."""
    if not path.is_file():
        raise ProvinceError(f"CSV provinsi tidak ditemukan: {path}")

    provinces: list[Province] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"no", "city", "province", "latitude", "longitude"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ProvinceError(f"Kolom CSV provinsi hilang: {sorted(missing)}")
        for row in reader:
            try:
                provinces.append(
                    Province(
                        number=int(row["no"]),
                        city=row["city"].strip(),
                        province=row["province"].strip(),
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ProvinceError(f"Baris provinsi tidak valid: {row!r}") from exc

    if not provinces:
        raise ProvinceError(f"CSV provinsi kosong: {path}")
    if len({item.province for item in provinces}) != len(provinces):
        raise ProvinceError("Nama provinsi duplikat di CSV referensi")
    return provinces


def haversine_km(
    latitude1: np.ndarray | Sequence[float],
    longitude1: np.ndarray | Sequence[float],
    latitude2: np.ndarray | Sequence[float],
    longitude2: np.ndarray | Sequence[float],
) -> np.ndarray:
    """Jarak great-circle dalam kilometer; input derajat."""
    lat1 = np.radians(np.asarray(latitude1, dtype=float))
    lon1 = np.radians(np.asarray(longitude1, dtype=float))
    lat2 = np.radians(np.asarray(latitude2, dtype=float))
    lon2 = np.radians(np.asarray(longitude2, dtype=float))

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = np.sin(delta_lat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2.0) ** 2
    return EARTH_RADIUS_KM * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def assign_nearest_province(
    latitudes: Sequence[float] | np.ndarray,
    longitudes: Sequence[float] | np.ndarray,
    provinces: Sequence[Province] | None = None,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> ProvinceMatch:
    """Petakan setiap titik ke ibu kota provinsi terdekat.

    Titik dengan koordinat tidak valid mendapat ``province=None`` dan jarak NaN.
    """
    references = list(provinces or load_provinces())
    if not references:
        raise ProvinceError("Daftar provinsi kosong")
    if chunk_size < 1:
        raise ValueError("chunk_size harus >= 1")

    lat = np.asarray(latitudes, dtype=float)
    lon = np.asarray(longitudes, dtype=float)
    if lat.shape != lon.shape:
        raise ValueError("latitude dan longitude harus sama panjang")
    if lat.ndim != 1:
        lat = lat.reshape(-1)
        lon = lon.reshape(-1)

    names = np.array([item.province for item in references], dtype=object)
    cities = np.array([item.city for item in references], dtype=object)
    ref_lat = np.radians(np.array([item.latitude for item in references], dtype=float))
    ref_lon = np.radians(np.array([item.longitude for item in references], dtype=float))
    ref_lat_rad = ref_lat[None, :]
    ref_lon_rad = ref_lon[None, :]

    result_index = np.full(lat.shape[0], -1, dtype=np.int32)
    result_distance = np.full(lat.shape[0], np.nan, dtype=float)
    valid = np.isfinite(lat) & np.isfinite(lon)

    for start in range(0, lat.shape[0], chunk_size):
        stop = min(start + chunk_size, lat.shape[0])
        chunk_lat = lat[start:stop]
        chunk_lon = lon[start:stop]
        chunk_valid = valid[start:stop]

        point_lat = np.radians(chunk_lat)[:, None]
        point_lon = np.radians(chunk_lon)[:, None]
        delta_lat = ref_lat_rad - point_lat
        delta_lon = ref_lon_rad - point_lon
        a = (
            np.sin(delta_lat / 2.0) ** 2
            + np.cos(point_lat) * np.cos(ref_lat_rad) * np.sin(delta_lon / 2.0) ** 2
        )
        distances = EARTH_RADIUS_KM * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
        distances[~chunk_valid, :] = np.inf

        nearest = np.argmin(distances, axis=1)
        picked = distances[np.arange(distances.shape[0]), nearest]
        picked[~chunk_valid] = np.nan

        result_index[start:stop] = np.where(chunk_valid, nearest, -1)
        result_distance[start:stop] = picked

    matched_province = np.full(lat.shape[0], None, dtype=object)
    matched_city = np.full(lat.shape[0], None, dtype=object)
    valid_index = result_index >= 0
    matched_province[valid_index] = names[result_index[valid_index]]
    matched_city[valid_index] = cities[result_index[valid_index]]

    return ProvinceMatch(
        province=matched_province,
        city=matched_city,
        distance_km=result_distance,
    )
