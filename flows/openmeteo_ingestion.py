"""Prefect flow for Open-Meteo raw ingestion into Garage Bronze.

Run manually from the repository root:

    python -m flows.openmeteo_ingestion --limit 2
    python -m flows.openmeteo_ingestion
    python -m flows.openmeteo_ingestion --verify-only <run_id>

No Prefect deployment or schedule is created here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.config import Settings, load_dotenv  # noqa: E402

load_dotenv(".env")


def _configure_prefect_ephemeral_if_needed() -> None:
    """Use a local ephemeral API unless the caller configured a real server."""

    if os.environ.get("PREFECT_API_URL") or os.environ.get("PREFECT_PROFILES_PATH"):
        return

    profile_dir = Path(tempfile.gettempdir()) / "karhutla-prefect"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profiles = profile_dir / "profiles.toml"
    profiles.write_text(
        'active = "ephemeral"\n\n'
        "[profiles.ephemeral]\n"
        'PREFECT_SERVER_EPHEMERAL_ENABLED = "true"\n',
        encoding="utf-8",
    )
    os.environ["PREFECT_PROFILES_PATH"] = str(profiles)
    os.environ.setdefault("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "true")


_configure_prefect_ephemeral_if_needed()

from prefect import flow, get_run_logger, task  # noqa: E402

from common.storage import BronzeStore  # noqa: E402
from ingest.openmeteo.client import OpenMeteoClient  # noqa: E402
from ingest.openmeteo.ingest import ingest_cities, new_run_id, verify_run  # noqa: E402
from ingest.openmeteo.locations import City, load_cities  # noqa: E402


@task(name="ingest-open-meteo-cities", log_prints=True)
def ingest_cities_task(
    cities_payload: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    logger = get_run_logger()
    settings = Settings.from_env()
    cities = [
        City(
            name=item["name"],
            province=item["province"],
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            number=item.get("no"),
        )
        for item in cities_payload
    ]

    store = BronzeStore(settings.garage)
    store.ensure_bucket()

    with OpenMeteoClient(settings.openmeteo) as client:
        manifest, key = ingest_cities(
            cities,
            client=client,
            store=store,
            run_id=run_id,
            settings=settings,
        )

    logger.info("Manifest: %s", key)
    logger.info("Summary: %s", manifest["summary"])
    if manifest["failures"]:
        logger.error("Failures: %d", len(manifest["failures"]))

    return {
        "run_id": run_id,
        "manifest_key": key,
        "status": manifest["status"],
        "summary": manifest["summary"],
        "failures": manifest["failures"],
    }


@flow(name="open-meteo-bronze", log_prints=True)
def open_meteo_bronze_ingestion(
    cities_payload: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    result = ingest_cities_task(cities_payload, run_id)
    if result["status"] != "success":
        raise RuntimeError(
            f"Open-Meteo ingestion finished with status={result['status']} "
            f"({len(result['failures'])} dataset failure(s)); see manifest "
            f"{result['manifest_key']}"
        )
    return result


@flow(name="open-meteo-bronze-daily", log_prints=True)
def daily_ingestion(limit: int | None = None) -> dict[str, Any]:
    """Entrypoint untuk Prefect deployment: muat daftar kota, lalu ingest.

    Dipakai `prefect.yaml`. Kalau dijalankan manual, lebih mudah memakai
    `python -m flows.openmeteo_ingestion`.
    """
    settings = Settings.from_env()
    cities = load_cities(settings.openmeteo.location_csv, limit=limit)
    payload = [city.as_dict() for city in cities]
    return open_meteo_bronze_ingestion(payload, new_run_id())


def verify(run_id: str) -> dict[str, Any]:
    settings = Settings.from_env()
    store = BronzeStore(settings.garage)
    return verify_run(store, run_id, prefix=settings.garage.prefix)


def _parse_names(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open-Meteo to Garage Bronze ingestion")
    parser.add_argument("--cities", help="Comma-separated city names or slugs")
    parser.add_argument("--limit", type=int, help="Ingest only the first N cities")
    parser.add_argument("--run-id", help="Explicit run id; default is generated")
    parser.add_argument(
        "--verify-only",
        metavar="RUN_ID",
        help="Read back an existing run without fetching Open-Meteo again",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        result = verify(args.verify_only)
        _print_json(result)
        return 0 if result["ok"] else 1

    settings = Settings.from_env()
    cities = load_cities(
        settings.openmeteo.location_csv,
        limit=args.limit,
        names=_parse_names(args.cities),
    )
    run_id = args.run_id or new_run_id()
    payload = [city.as_dict() for city in cities]

    print(f"run_id={run_id} cities={len(cities)} bucket={settings.garage.bucket}")
    result = open_meteo_bronze_ingestion(payload, run_id)
    _print_json(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI must return a non-zero status
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
