"""Reference city list for Open-Meteo ingestion."""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"city", "province", "latitude", "longitude"}


class LocationError(RuntimeError):
    """Raised when the reference city list is missing or invalid."""


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")
    if not slug:
        raise LocationError(f"Cannot build a slug from {value!r}")
    return slug


@dataclass(frozen=True)
class City:
    name: str
    province: str
    latitude: float
    longitude: float
    # nomor urut opsional dari kolom "no" di CSV referensi
    number: int | None = None

    @property
    def slug(self) -> str:
        return slugify(f"{self.name} {self.province}")

    def as_dict(self) -> dict[str, str | float | int | None]:
        return {
            "no": self.number,
            "name": self.name,
            "province": self.province,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


def resolve_city_csv(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate

    repo_root = Path(__file__).resolve().parents[3]
    fallback = repo_root / candidate
    if fallback.is_file():
        return fallback

    raise LocationError(f"City reference CSV not found: {candidate}")


def load_cities(
    path: str | Path,
    *,
    limit: int | None = None,
    names: list[str] | None = None,
) -> list[City]:
    csv_path = resolve_city_csv(path)
    cities: list[City] = []
    seen: set[tuple[str, str]] = set()
    seen_slugs: set[str] = set()
    seen_numbers: set[int] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise LocationError(f"City reference CSV has no header: {csv_path}")
        missing = REQUIRED_COLUMNS - {name.strip() for name in reader.fieldnames}
        if missing:
            raise LocationError(
                f"City reference CSV is missing columns: {', '.join(sorted(missing))}"
            )

        for row_number, row in enumerate(reader, start=2):
            name = (row.get("city") or "").strip()
            province = (row.get("province") or "").strip()
            if not name or not province:
                raise LocationError(f"Empty city/province at {csv_path}:{row_number}")

            try:
                latitude = float((row.get("latitude") or "").strip())
                longitude = float((row.get("longitude") or "").strip())
            except ValueError as exc:
                raise LocationError(
                    f"Invalid latitude/longitude at {csv_path}:{row_number}"
                ) from exc

            if not -11.5 <= latitude <= 6.5:
                raise LocationError(
                    f"Latitude out of Indonesian range at {csv_path}:{row_number}: {latitude}"
                )
            if not 94.0 <= longitude <= 142.0:
                raise LocationError(
                    f"Longitude out of Indonesian range at {csv_path}:{row_number}: {longitude}"
                )

            key = (name.casefold(), province.casefold())
            if key in seen:
                raise LocationError(f"Duplicate city/province at {csv_path}:{row_number}: {name}")
            seen.add(key)

            raw_number = (row.get("no") or "").strip()
            number: int | None = None
            if raw_number:
                try:
                    number = int(raw_number)
                except ValueError as exc:
                    raise LocationError(
                        f"Invalid 'no' column at {csv_path}:{row_number}: {raw_number!r}"
                    ) from exc
                if number < 1:
                    raise LocationError(
                        f"'no' must be positive at {csv_path}:{row_number}: {number}"
                    )
                if number in seen_numbers:
                    raise LocationError(
                        f"Duplicate 'no' at {csv_path}:{row_number}: {number}"
                    )
                seen_numbers.add(number)

            city = City(
                name=name,
                province=province,
                latitude=latitude,
                longitude=longitude,
                number=number,
            )
            if city.slug in seen_slugs:
                raise LocationError(f"Duplicate city slug at {csv_path}:{row_number}: {city.slug}")
            seen_slugs.add(city.slug)
            cities.append(city)

    if not cities:
        raise LocationError(f"City reference CSV is empty: {csv_path}")

    if names:
        wanted = {value.strip().casefold() for value in names if value.strip()}
        cities = [
            city
            for city in cities
            if city.name.casefold() in wanted or city.slug.casefold() in wanted
        ]
        if not cities:
            raise LocationError("No cities matched the requested --cities filter")

    if limit is not None:
        if limit < 0:
            raise LocationError("--limit must be zero or greater")
        cities = cities[:limit]

    if not cities:
        raise LocationError("No cities selected for ingestion")

    logger.info("Loaded %d cities from %s", len(cities), csv_path)
    return cities
