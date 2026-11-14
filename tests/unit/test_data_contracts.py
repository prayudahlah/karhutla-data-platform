from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "docs" / "data-contracts"
CONTRACTS = sorted(CONTRACT_DIR.glob("*.yml"))
EXPECTED_CONTRACTS = {
    "firms_hotspot",
    "hotspot_scar_label",
    "mcd64a1_burn_scar",
    "open_meteo_air_quality",
    "open_meteo_weather",
}
REQUIRED_FIELDS = {
    "name",
    "owner",
    "layer",
    "status",
    "location",
    "grain",
    "schema",
    "freshness",
    "retention",
    "classification",
    "quality_rules",
    "consumers",
}
ALLOWED_STATUSES = {"draft", "implemented", "deprecated"}
ALLOWED_TYPES = {"boolean", "date", "double", "integer", "string", "timestamp"}


def _load(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} harus berisi mapping YAML"
    return payload


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.stem)
def test_contract_has_required_fields(path: Path) -> None:
    contract = _load(path)
    missing = REQUIRED_FIELDS - contract.keys()
    assert not missing, f"{path.name} kehilangan field: {sorted(missing)}"


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.stem)
def test_contract_identity_and_status(path: Path) -> None:
    contract = _load(path)
    assert contract["name"] == path.stem
    assert contract["layer"] == "silver"
    assert contract["status"] in ALLOWED_STATUSES
    assert isinstance(contract["owner"], str) and contract["owner"].startswith("Kelompok 8")
    assert contract["classification"] == "public"
    assert isinstance(contract["retention"], str) and contract["retention"]


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.stem)
def test_contract_location(path: Path) -> None:
    location = _load(path)["location"]
    assert isinstance(location, dict)
    assert "Garage" in location["storage"]
    assert location["bucket"] == "lakehouse"
    assert location["prefix"].startswith("silver/")
    assert ".parquet" in location["pattern"] and "=" in location["pattern"]

    publish = location["publish"]
    assert publish["materialization"] == "external parquet (dbt-duckdb)"
    assert publish["local_root"].startswith("data/silver/published/")
    assert publish["uploader"] == "python -m batch.silver.sync push"


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.stem)
def test_contract_schema_types(path: Path) -> None:
    schema = _load(path)["schema"]
    assert isinstance(schema, dict) and schema
    for column, definition in schema.items():
        assert isinstance(definition, dict), f"{path.name}:{column} bukan mapping"
        assert definition.get("type") in ALLOWED_TYPES, f"{path.name}:{column} tipe tidak valid"
        if "nullable" in definition:
            assert isinstance(definition["nullable"], bool)


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.stem)
def test_contract_documentation_fields(path: Path) -> None:
    contract = _load(path)
    assert isinstance(contract["freshness"], dict)
    assert contract["freshness"].get("expected")
    assert isinstance(contract["quality_rules"], list) and contract["quality_rules"]
    assert isinstance(contract["consumers"], list) and contract["consumers"]
    assert all(isinstance(item, str) and item for item in contract["consumers"])


def test_expected_contract_files_exist() -> None:
    assert {path.stem for path in CONTRACTS} == EXPECTED_CONTRACTS


def test_firms_contract_has_final_date_partition() -> None:
    contract = _load(CONTRACT_DIR / "firms_hotspot.yml")
    assert contract["schema"]["date"]["type"] == "date"
    assert contract["deduplication"]["key"] == "event_id"
    assert "source_file" in contract["deduplication"]["tie_break"]


def test_open_meteo_contracts_use_province_city_timestamp_key() -> None:
    for filename in ("open_meteo_weather.yml", "open_meteo_air_quality.yml"):
        contract = _load(CONTRACT_DIR / filename)
        assert contract["deduplication"]["key"] == ["province", "city", "ts_utc"]
        assert contract["location"]["publish"]["local_root"].startswith(
            "data/silver/published/open_meteo/"
        )


def test_mcd64a1_contract_documents_partition_exception() -> None:
    contract = _load(CONTRACT_DIR / "mcd64a1_burn_scar.yml")
    schema = contract["schema"]
    normalized_schema = contract["normalized_schema"]

    assert {"pixel_row", "pixel_col"} <= schema.keys()
    assert {"row", "col"} <= normalized_schema.keys()
    assert "burn_date=" in contract["location"]["pattern"]
    assert "burn_date" in contract["partition_note"].lower()
    assert contract["supporting_tables"]["tiles"]["final_prefix"].endswith("tiles.parquet")
    assert contract["supporting_tables"]["coverage"]["normalized_prefix"].endswith(
        "dataset=coverage"
    )


def test_hotspot_label_contract_matches_macro() -> None:
    contract = _load(CONTRACT_DIR / "hotspot_scar_label.yml")
    macro = REPO_ROOT / contract["tier_rules"]["macro"]

    assert macro.is_file()
    assert set(contract["tier_rules"]["tiers"]) == {"kuat", "sedang", "lemah", "kandidat"}
    assert contract["deduplication"]["key"] == "event_id"
    assert "firms_hotspot" in contract["source_models"]
    assert "mcd64a1_burn_scar" in contract["source_models"]
