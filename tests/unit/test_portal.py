from __future__ import annotations

import json

from fastapi.testclient import TestClient

from serving.main import create_app
from serving.settings import Settings


def _settings(tmp_path):
    return Settings(gold_root=tmp_path, catalog_root=tmp_path)


def _write(tmp_path, catalog, lineage=None):
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    if lineage is not None:
        (tmp_path / "lineage.json").write_text(json.dumps(lineage), encoding="utf-8")


def _catalog():
    return {
        "layer": "gold",
        "run_id": "run-uji",
        "table_count": 1,
        "tables": [
            {
                "name": "cell_daily",
                "owner": "Kelompok 8",
                "layer": "gold",
                "status": "implemented",
                "classification": "public",
                "retention": "mengikuti Silver",
                "grain": "satu baris per sel per hari",
                "business_key": ["cell_id", "date"],
                "location": {"storage": "Garage", "prefix": "gold/cell_daily"},
                "freshness": {"expected": "harian"},
                "quality_rules": ["cell_id unik"],
                "consumers": ["dashboard"],
                "source_models": ["hotspot_scar_label"],
                "schema": {
                    "cell_id": {"type": "string", "description": "indeks sel"},
                    "label_risk": {"type": "integer"},
                },
            }
        ],
    }


def _lineage():
    return {
        "layer": "gold",
        "run_id": "run-uji",
        "node_count": 2,
        "edge_count": 1,
        "nodes": [
            {"id": "firms", "layer": "bronze", "type": "source"},
            {"id": "cell_daily", "layer": "gold", "type": "table"},
        ],
        "edges": [{"from": "firms", "to": "cell_daily", "note": "dbt ref"}],
    }


def test_portal_shows_notice_without_catalog(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/")

    assert response.status_code == 200
    assert "Katalog belum ada" in response.text


def test_catalog_lists_tables(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/catalog")

    assert response.status_code == 200
    assert "cell_daily" in response.text
    assert "Terpasang" in response.text


def test_dataset_page_renders_schema(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/catalog/cell_daily")

    assert response.status_code == 200
    assert "label_risk" in response.text
    assert "indeks sel" in response.text


def test_unknown_dataset_returns_404(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    assert client.get("/catalog/tidak-ada").status_code == 404


def test_lineage_page_lists_edges(tmp_path):
    _write(tmp_path, _catalog(), _lineage())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/lineage")

    assert response.status_code == 200
    assert "firms" in response.text
    assert "dbt ref" in response.text


def test_admin_page_shows_identity_header(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/admin", headers={"Remote-User": "admin", "Remote-Groups": "admin"})

    assert response.status_code == 200
    assert "admin" in response.text


def test_dashboard_placeholder_returns_404(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/dashboard")

    assert response.status_code == 404
    assert "belum diimplementasikan" in response.text


def test_header_shows_logged_in_user(tmp_path):
    _write(tmp_path, _catalog())
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/", headers={"Remote-User": "viewer"})

    assert response.status_code == 200
    assert "viewer" in response.text
    assert "Keluar" in response.text


def test_dashboard_button_points_to_metabase(tmp_path):
    _write(tmp_path, _catalog())
    settings = Settings(
        gold_root=tmp_path, catalog_root=tmp_path, metabase_url="https://mb.contoh"
    )
    client = TestClient(create_app(settings))

    response = client.get("/", headers={"Remote-User": "viewer"})

    assert 'href="https://mb.contoh"' in response.text
