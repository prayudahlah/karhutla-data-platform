"""Environment-driven configuration for the batch ingestion jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

WEATHER_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "soil_moisture_0_to_7cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)

AIR_QUALITY_VARIABLES: tuple[str, ...] = (
    "pm2_5",
    "pm10",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "aerosol_optical_depth",
)


class ConfigError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> None:
    """Load a minimal .env file without adding a python-dotenv dependency.

    Existing environment variables win unless ``override`` is true. This keeps
    container/CI injected values authoritative.
    """

    env_path = Path(path)
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def _get(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or not value.strip()):
        raise ConfigError(f"Missing required environment variable: {name}")
    return "" if value is None else value.strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _get_floats(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    raw = _get(name, ",".join(f"{value:g}" for value in default))
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) != len(default):
        raise ConfigError(
            f"{name} must contain {len(default)} comma-separated numbers, got {raw!r}"
        )
    try:
        return tuple(float(part) for part in parts)
    except ValueError as exc:
        raise ConfigError(f"{name} must contain numbers, got {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


@dataclass(frozen=True)
class GarageSettings:
    endpoint: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    prefix: str = "bronze/open_meteo"
    force_path_style: bool = True
    connect_timeout: int = 10
    read_timeout: int = 60
    max_attempts: int = 3

    @classmethod
    def from_env(cls) -> GarageSettings:
        return cls(
            endpoint=_get("GARAGE_ENDPOINT", required=True),
            region=_get("GARAGE_REGION", "garage"),
            access_key_id=_get("GARAGE_ACCESS_KEY_ID", required=True),
            secret_access_key=_get("GARAGE_SECRET_ACCESS_KEY", required=True),
            bucket=_get("GARAGE_BUCKET", "lakehouse", required=True),
            prefix=_get("BRONZE_PREFIX", "bronze/open_meteo").strip("/"),
            force_path_style=_get_bool("GARAGE_FORCE_PATH_STYLE", True),
            connect_timeout=_get_int("GARAGE_CONNECT_TIMEOUT_SECONDS", 10),
            read_timeout=_get_int("GARAGE_READ_TIMEOUT_SECONDS", 60),
            max_attempts=_get_int("GARAGE_MAX_ATTEMPTS", 3),
        )


@dataclass(frozen=True)
class OpenMeteoSettings:
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    timezone: str = "Asia/Jakarta"
    forecast_days: int = 3
    past_days: int = 0
    timeout_seconds: float = 30.0
    max_retries: int = 3
    city_csv: Path = Path("resources/indonesia_cities.csv")
    provinces_csv: Path = Path("resources/indonesia_provinces.csv")
    # province = satu titik per provinsi (ibu kota), city = 98 kota
    location_level: str = "province"

    @property
    def location_csv(self) -> Path:
        """File referensi lokasi sesuai level yang dipilih."""
        return self.provinces_csv if self.location_level == "province" else self.city_csv

    @classmethod
    def from_env(cls) -> OpenMeteoSettings:
        level = _get("OPENMETEO_LOCATION_LEVEL", cls.location_level).lower()
        if level not in {"province", "city"}:
            raise ConfigError(
                f"OPENMETEO_LOCATION_LEVEL must be 'province' or 'city', got {level!r}"
            )
        return cls(
            weather_url=_get("OPENMETEO_WEATHER_URL", cls.weather_url),
            air_quality_url=_get("OPENMETEO_AIR_QUALITY_URL", cls.air_quality_url),
            timezone=_get("OPENMETEO_TIMEZONE", cls.timezone),
            forecast_days=_get_int("OPENMETEO_FORECAST_DAYS", cls.forecast_days),
            past_days=_get_int("OPENMETEO_PAST_DAYS", cls.past_days),
            timeout_seconds=_get_float("OPENMETEO_TIMEOUT_SECONDS", cls.timeout_seconds),
            max_retries=_get_int("OPENMETEO_MAX_RETRIES", cls.max_retries),
            city_csv=Path(_get("OPENMETEO_CITY_CSV", str(cls.city_csv))),
            provinces_csv=Path(_get("OPENMETEO_PROVINCES_CSV", str(cls.provinces_csv))),
            location_level=level,
        )


@dataclass(frozen=True)
class FirmsBronzeSettings:
    """Prefix Bronze untuk stream FIRMS (ditulis consumer di node batch)."""

    prefix: str = "bronze/firms"

    @classmethod
    def from_env(cls) -> FirmsBronzeSettings:
        return cls(prefix=_get("BRONZE_PREFIX_FIRMS", cls.prefix).strip("/"))


@dataclass(frozen=True)
class BurnedAreaSettings:
    """Ingest produk burned area (MCD64A1) dari LP DAAC ke Bronze.

    Token Earthdata tidak wajib ada saat konfigurasi dibaca, supaya tes dan
    perintah offline tidak butuh kredensial. Keberadaannya diperiksa saat
    unduhan benar-benar dijalankan.
    """

    cmr_url: str = "https://cmr.earthdata.nasa.gov/search/granules.json"
    short_name: str = "MCD64A1"
    version: str = "061"
    token: str = ""
    bronze_prefix: str = "bronze/mcd64a1"
    bbox: tuple[float, float, float, float] = (95.0, -11.0, 141.0, 6.0)
    timeout_seconds: float = 60.0
    max_retries: int = 3
    page_size: int = 2000

    @classmethod
    def from_env(cls) -> BurnedAreaSettings:
        bbox = _get_floats("BURNED_AREA_BBOX", (95.0, -11.0, 141.0, 6.0))
        west, south, east, north = bbox
        if west >= east or south >= north:
            raise ConfigError(
                "BURNED_AREA_BBOX must be west,south,east,north with west<east and south<north"
            )
        return cls(
            cmr_url=_get("CMR_GRANULES_URL", cls.cmr_url),
            short_name=_get("BURNED_AREA_SHORT_NAME", cls.short_name),
            version=_get("BURNED_AREA_VERSION", cls.version),
            token=_get("EARTHDATA_TOKEN"),
            bronze_prefix=_get("BRONZE_PREFIX_MCD64A1", cls.bronze_prefix).strip("/"),
            bbox=(west, south, east, north),
            timeout_seconds=_get_float("BURNED_AREA_TIMEOUT_SECONDS", cls.timeout_seconds),
            max_retries=_get_int("BURNED_AREA_MAX_RETRIES", cls.max_retries),
            page_size=_get_int("BURNED_AREA_PAGE_SIZE", cls.page_size),
        )


@dataclass(frozen=True)
class FirmsBackfillSettings:
    """Tarik hotspot historis lewat area API FIRMS.

    Kunci MAP_KEY sama dengan yang dipakai producer di node stream, tapi di sini
    dibaca dari environment node batch.
    """

    map_key: str = ""
    bbox: tuple[float, float, float, float] = (95.0, -11.0, 141.0, 6.0)
    sources: tuple[str, ...] = (
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA21_NRT",
        "MODIS_NRT",
    )
    window_days: int = 5
    timeout_seconds: float = 60.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> FirmsBackfillSettings:
        bbox = _get_floats("FIRMS_BACKFILL_BBOX", cls.bbox)
        west, south, east, north = bbox
        if west >= east or south >= north:
            raise ConfigError(
                "FIRMS_BACKFILL_BBOX must be west,south,east,north with west<east and south<north"
            )
        raw_sources = _get("FIRMS_BACKFILL_SOURCES", ",".join(cls.sources))
        sources = tuple(part.strip() for part in raw_sources.split(",") if part.strip())
        if not sources:
            raise ConfigError("FIRMS_BACKFILL_SOURCES tidak boleh kosong")
        return cls(
            map_key=_get("FIRMS_MAP_KEY"),
            bbox=(west, south, east, north),
            sources=sources,
            window_days=_get_int("FIRMS_BACKFILL_WINDOW_DAYS", cls.window_days),
            timeout_seconds=_get_float("FIRMS_BACKFILL_TIMEOUT_SECONDS", cls.timeout_seconds),
            max_retries=_get_int("FIRMS_BACKFILL_MAX_RETRIES", cls.max_retries),
        )


@dataclass(frozen=True)
class Settings:
    garage: GarageSettings
    openmeteo: OpenMeteoSettings
    # punya default supaya konstruksi Settings(...) lama tetap valid
    firms_bronze: FirmsBronzeSettings = field(default_factory=FirmsBronzeSettings)
    burned_area: BurnedAreaSettings = field(default_factory=BurnedAreaSettings.from_env)
    firms_backfill: FirmsBackfillSettings = field(
        default_factory=FirmsBackfillSettings.from_env
    )

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        if env_file is not None:
            load_dotenv(env_file)
        return cls(
            garage=GarageSettings.from_env(),
            openmeteo=OpenMeteoSettings.from_env(),
            firms_bronze=FirmsBronzeSettings.from_env(),
            burned_area=BurnedAreaSettings.from_env(),
            firms_backfill=FirmsBackfillSettings.from_env(),
        )
