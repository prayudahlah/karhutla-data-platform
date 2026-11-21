"""Pembagian wilayah untuk spatial holdout.

Provinsi dikelompokkan menjadi tujuh wilayah. Empat wilayah dipakai sebagai
fold konfirmasi, satu sebagai wilayah pengembangan, dua tidak dipakai karena
terlalu sedikit kebakaran pada jendela test.
"""

from __future__ import annotations

PROVINCE_TO_REGION: dict[str, str] = {
    # Sumatra
    "Aceh": "Sumatra",
    "Sumatera Utara": "Sumatra",
    "Sumatera Barat": "Sumatra",
    "Riau": "Sumatra",
    "Kepulauan Riau": "Sumatra",
    "Jambi": "Sumatra",
    "Bengkulu": "Sumatra",
    "Sumatera Selatan": "Sumatra",
    "Kepulauan Bangka Belitung": "Sumatra",
    "Lampung": "Sumatra",
    # Jawa
    "DKI Jakarta": "Jawa",
    "Jawa Barat": "Jawa",
    "Banten": "Jawa",
    "Jawa Tengah": "Jawa",
    "DI Yogyakarta": "Jawa",
    "Jawa Timur": "Jawa",
    # Kalimantan
    "Kalimantan Barat": "Kalimantan",
    "Kalimantan Tengah": "Kalimantan",
    "Kalimantan Selatan": "Kalimantan",
    "Kalimantan Timur": "Kalimantan",
    "Kalimantan Utara": "Kalimantan",
    # Sulawesi
    "Sulawesi Utara": "Sulawesi",
    "Gorontalo": "Sulawesi",
    "Sulawesi Tengah": "Sulawesi",
    "Sulawesi Barat": "Sulawesi",
    "Sulawesi Selatan": "Sulawesi",
    "Sulawesi Tenggara": "Sulawesi",
    # Bali dan Nusa Tenggara
    "Bali": "Bali_Nusa",
    "Nusa Tenggara Barat": "Bali_Nusa",
    "Nusa Tenggara Timur": "Bali_Nusa",
    # Maluku
    "Maluku": "Maluku",
    "Maluku Utara": "Maluku",
    # Papua
    "Papua": "Papua",
    "Papua Barat": "Papua",
    "Papua Barat Daya": "Papua",
    "Papua Tengah": "Papua",
    "Papua Pegunungan": "Papua",
    "Papua Selatan": "Papua",
}

ALL_REGIONS: tuple[str, ...] = tuple(sorted(set(PROVINCE_TO_REGION.values())))

# Fold konfirmasi: wilayah dengan cukup positif pada jendela test 19-23 Sep.
CONFIRMATION_REGIONS: tuple[str, ...] = ("Kalimantan", "Sumatra", "Papua", "Maluku")

# Wilayah pengembangan untuk iterasi; bukan bukti konfirmasi.
DEVELOPMENT_REGION = "Sulawesi"

# Kolom yang berasal dari lokasi dan dibuang pada ablasi tanpa lokasi.
LOCATION_FEATURES: tuple[str, ...] = (
    "province",
    "center_lat",
    "center_lon",
    "province_distance_km",
)


class RegionError(ValueError):
    """Wilayah tidak dikenal atau data provinsi tidak lengkap."""


def region_of(province: str) -> str:
    try:
        return PROVINCE_TO_REGION[province]
    except KeyError as exc:
        raise RegionError(f"provinsi tidak dikenal: {province}") from exc


def region_slug(region: str) -> str:
    return region.lower().replace(" ", "-")


def validate_regions(regions: tuple[str, ...] | list[str]) -> None:
    unknown = sorted(set(regions) - set(ALL_REGIONS))
    if unknown:
        raise RegionError(f"wilayah tidak dikenal: {', '.join(unknown)}")
