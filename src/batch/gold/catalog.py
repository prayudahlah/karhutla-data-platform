"""Hasilkan ``catalog.json`` dan ``lineage.json`` untuk layer Gold.

Katalog dibangun dari kontrak di ``docs/data-contracts`` supaya owner,
klasifikasi, dan retensi hanya punya satu sumber kebenaran. Lineage memakai
peta sumber -> Silver -> Gold; detail model antara (``int_*``) sengaja tidak
dimasukkan agar alurnya tetap mudah dibaca.

Jalankan setelah ``dbt build --select tag:gold``::

    python -m batch.gold.catalog --run-id <run_id>

Berkas ditulis ke ``data/gold/_catalog`` secara default.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

GOLD_TABLES: tuple[str, ...] = (
    "cell_daily",
    "province_daily",
    "burn_scar_monthly",
    "risk_prediction_daily",
)

# Tiga tabel yang sudah punya model dbt dan kontrak.
IMPLEMENTED_TABLES: tuple[str, ...] = (
    "cell_daily",
    "province_daily",
    "burn_scar_monthly",
)

# Sumber mentah -> dataset Silver yang diturunkan darinya.
RAW_TO_SILVER: dict[str, tuple[str, ...]] = {
    "firms": ("firms_hotspot", "hotspot_scar_label"),
    "open_meteo": ("open_meteo_weather", "open_meteo_air_quality"),
    "mcd64a1": ("mcd64a1_burn_scar", "mcd64a1_tiles"),
}

SILVER_TABLES: tuple[str, ...] = tuple(
    sorted({name for names in RAW_TO_SILVER.values() for name in names})
)

# Kontrak menyimpan source_models; model antara int_* tidak ikut lineage.
CATALOG_FIELDS: tuple[str, ...] = (
    "name",
    "owner",
    "layer",
    "status",
    "classification",
    "retention",
    "grain",
    "business_key",
    "location",
    "freshness",
    "quality_rules",
    "consumers",
    "source_models",
    "schema",
)

DEFAULT_CONTRACT_DIR = Path("docs/data-contracts")
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("GOLD_CATALOG_ROOT", "data/gold/_catalog")
)

# risk_prediction_daily belum punya model karena ML ditunda. Entri ini tetap
# dicatat supaya katalog memuat 4 tabel Gold sesuai checklist.
PLANNED_TABLE: dict[str, Any] = {
    "name": "risk_prediction_daily",
    "owner": "Kelompok 8 - Batch",
    "layer": "gold",
    "status": "planned",
    "classification": "public",
    "retention": "mengikuti cell_daily; dibangun ulang oleh inference ML",
    "grain": "satu baris per input_record_id",
    "business_key": ["input_record_id"],
    "location": {
        "storage": "Garage (S3-compatible)",
        "bucket": "lakehouse",
        "prefix": "gold/risk_prediction_daily",
        "pattern": "date=YYYY-MM-DD/*.parquet",
        "publish": {
            "materialization": "external parquet (dbt-duckdb)",
            "local_root": "data/gold/published/risk_prediction_daily",
            "uploader": None,
        },
    },
    "freshness": {
        "expected": "harian setelah Gold selesai dan model tersedia",
        "alert_threshold": "belum ada sampai inference berjalan",
        "measured_by": "predicted_at",
    },
    "quality_rules": [
        "input_record_id unik",
        "score berada di rentang 0..1",
        "status hanya berisi nilai yang disepakati",
    ],
    "consumers": ["dashboard prediksi", "FastAPI read-only"],
    "source_models": ["cell_daily"],
    "schema": {
        "input_record_id": {
            "type": "string",
            "description": "kunci baris cell_daily yang diskor",
        },
        "model_version": {"type": "string"},
        "predicted_at": {"type": "timestamp"},
        "score": {"type": "double"},
        "status": {"type": "string"},
    },
}


def _load_contract(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Kontrak bukan mapping YAML: {path}")
    return payload


def build_catalog(
    contract_dir: Path = DEFAULT_CONTRACT_DIR,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Bangun katalog 4 tabel Gold dari kontrak."""
    tables: list[dict[str, Any]] = []
    for name in IMPLEMENTED_TABLES:
        contract = _load_contract(contract_dir / f"{name}.yml")
        tables.append({field: contract[field] for field in CATALOG_FIELDS})
    tables.append(dict(PLANNED_TABLE))
    return {
        "layer": "gold",
        "run_id": run_id,
        "table_count": len(tables),
        "tables": tables,
    }


def build_lineage(
    contract_dir: Path = DEFAULT_CONTRACT_DIR,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Bangun lineage Bronze -> Silver -> Gold dari kontrak."""
    silver_to_gold: dict[str, list[str]] = {}
    for name in IMPLEMENTED_TABLES:
        contract = _load_contract(contract_dir / f"{name}.yml")
        sources = {
            source
            for source in contract.get("source_models", [])
            if source in SILVER_TABLES or source in GOLD_TABLES
        }
        silver_to_gold[name] = sorted(sources)
    silver_to_gold["risk_prediction_daily"] = ["cell_daily"]

    nodes: list[dict[str, str]] = []
    for raw in RAW_TO_SILVER:
        nodes.append({"id": raw, "layer": "bronze", "type": "source"})
    for silver in SILVER_TABLES:
        nodes.append({"id": silver, "layer": "silver", "type": "dataset"})
    for gold in GOLD_TABLES:
        nodes.append({"id": gold, "layer": "gold", "type": "table"})

    edges: list[dict[str, str]] = []
    for raw, silver_datasets in RAW_TO_SILVER.items():
        for silver in silver_datasets:
            edges.append(
                {
                    "from": raw,
                    "to": silver,
                    "note": "normalisasi Silver",
                }
            )
    for gold, sources in silver_to_gold.items():
        for source in sources:
            edges.append(
                {
                    "from": source,
                    "to": gold,
                    "note": "dbt ref",
                }
            )

    return {
        "layer": "gold",
        "run_id": run_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def write_artifacts(
    output_dir: Path,
    catalog: dict[str, Any],
    lineage: dict[str, Any],
) -> list[Path]:
    """Tulis katalog dan lineage, kembalikan path yang dibuat."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, payload in (
        ("catalog.json", catalog),
        ("lineage.json", lineage),
    ):
        path = output_dir / filename
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hasilkan catalog.json dan lineage.json Gold"
    )
    parser.add_argument(
        "--contracts",
        default=str(DEFAULT_CONTRACT_DIR),
        help="folder kontrak YAML",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT_DIR),
        help="folder keluaran",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GOLD_RUN_ID"),
        help="penanda run, mis. tanggal build",
    )
    args = parser.parse_args(argv)

    contract_dir = Path(args.contracts)
    output_dir = Path(args.out)
    catalog = build_catalog(contract_dir, args.run_id)
    lineage = build_lineage(contract_dir, args.run_id)
    written = write_artifacts(output_dir, catalog, lineage)
    print(
        json.dumps(
            {
                "tables": catalog["table_count"],
                "nodes": lineage["node_count"],
                "edges": lineage["edge_count"],
                "files": [str(path) for path in written],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
