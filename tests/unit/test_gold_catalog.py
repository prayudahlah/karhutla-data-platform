from __future__ import annotations

import json
from pathlib import Path

from batch.gold.catalog import (
    GOLD_TABLES,
    SILVER_TABLES,
    build_catalog,
    build_lineage,
    write_artifacts,
)

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "docs" / "data-contracts"


def test_catalog_contains_four_gold_tables() -> None:
    catalog = build_catalog(CONTRACT_DIR, run_id="test-run")

    assert catalog["run_id"] == "test-run"
    assert catalog["table_count"] == 4
    assert [table["name"] for table in catalog["tables"]] == list(GOLD_TABLES)


def test_catalog_tables_have_owner_and_classification() -> None:
    catalog = build_catalog(CONTRACT_DIR)

    for table in catalog["tables"]:
        assert table["owner"].startswith("Kelompok 8")
        assert table["layer"] == "gold"
        assert table["classification"] == "public"
        assert table["retention"]
        assert table["location"]["prefix"].startswith("gold/")
        assert table["schema"]


def test_planned_table_is_marked() -> None:
    catalog = build_catalog(CONTRACT_DIR)
    planned = next(
        table for table in catalog["tables"] if table["name"] == "risk_prediction_daily"
    )

    assert planned["status"] == "planned"
    assert planned["source_models"] == ["cell_daily"]


def test_lineage_edges_connect_known_nodes() -> None:
    lineage = build_lineage(CONTRACT_DIR)

    node_ids = [node["id"] for node in lineage["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    node_set = set(node_ids)
    assert {"firms", "open_meteo", "mcd64a1"} <= node_set
    assert set(SILVER_TABLES) <= node_set
    assert set(GOLD_TABLES) <= node_set

    for edge in lineage["edges"]:
        assert edge["from"] in node_set
        assert edge["to"] in node_set

    pairs = {(edge["from"], edge["to"]) for edge in lineage["edges"]}
    assert ("firms", "firms_hotspot") in pairs
    assert ("cell_daily", "province_daily") in pairs
    assert ("mcd64a1_burn_scar", "burn_scar_monthly") in pairs
    assert ("cell_daily", "risk_prediction_daily") in pairs


def test_write_artifacts_creates_valid_json(tmp_path: Path) -> None:
    catalog = build_catalog(CONTRACT_DIR, run_id="2026-09")
    lineage = build_lineage(CONTRACT_DIR, run_id="2026-09")

    written = write_artifacts(tmp_path, catalog, lineage)

    assert [path.name for path in written] == ["catalog.json", "lineage.json"]
    catalog_payload = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    lineage_payload = json.loads((tmp_path / "lineage.json").read_text(encoding="utf-8"))
    assert catalog_payload["table_count"] == 4
    assert lineage_payload["run_id"] == "2026-09"
    assert lineage_payload["edge_count"] == len(lineage_payload["edges"])
