"""Siapkan isi katalog untuk template.

Kontrak Gold menyimpan ``location`` dan ``freshness`` sebagai objek bertingkat.
Portal menampilkannya sebagai daftar label-nilai supaya bisa dibaca, sambil tetap
menyimpan JSON asli di balik elemen ``details`` untuk audit.
"""

from __future__ import annotations

from typing import Any

LOCATION_LABELS = {
    "storage": "Storage",
    "bucket": "Bucket",
    "prefix": "Prefix",
    "pattern": "Pola berkas",
    "materialization": "Materialisasi",
    "table_format": "Format tabel",
    "iceberg_prefix": "Prefix Iceberg",
    "iceberg_warehouse": "Warehouse Iceberg",
    "local_root": "Akar lokal",
    "uploader": "Uploader",
    "publish_command": "Perintah publish",
    "role": "Peran",
    "staging": "Staging",
    "serving_reads": "Baca serving",
    "ml_reads": "Baca ML",
}

LOCATION_ORDER = [
    "storage",
    "bucket",
    "prefix",
    "pattern",
    "materialization",
    "table_format",
    "iceberg_prefix",
    "iceberg_warehouse",
    "local_root",
    "uploader",
    "publish_command",
    "role",
    "staging",
    "serving_reads",
    "ml_reads",
]

LOCATION_CODE = {"pattern", "publish_command", "iceberg_prefix", "local_root", "prefix"}

FRESHNESS_LABELS = {
    "expected": "Ekspektasi",
    "alert_threshold": "Ambang alert",
    "measured_by": "Diukur oleh",
}

FRESHNESS_ORDER = ["expected", "alert_threshold", "measured_by"]


def _scalar(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "ya" if value else "tidak"
    return str(value)


def location_view(location: dict[str, Any] | None) -> dict[str, Any]:
    """Ratakan objek lokasi, termasuk blok ``publish`` di dalamnya."""
    if not isinstance(location, dict):
        return {"rows": [], "note": "", "raw": location}

    merged: dict[str, Any] = {}
    for key, value in location.items():
        if isinstance(value, dict):
            merged.update(value)
        else:
            merged[key] = value

    rows = []
    for key in LOCATION_ORDER:
        if key not in merged or merged[key] in (None, ""):
            continue
        rows.append(
            {
                "key": key,
                "label": LOCATION_LABELS.get(key, key.replace("_", " ").capitalize()),
                "value": _scalar(merged[key]),
                "code": key in LOCATION_CODE,
            }
        )
    known = set(LOCATION_ORDER) | {"partition_note"}
    for key, value in merged.items():
        if key in known or isinstance(value, dict | list) or value in (None, ""):
            continue
        rows.append(
            {
                "key": key,
                "label": LOCATION_LABELS.get(key, key.replace("_", " ").capitalize()),
                "value": _scalar(value),
                "code": False,
            }
        )

    note = merged.get("partition_note") or ""
    return {
        "rows": rows,
        "note": note if isinstance(note, str) else "",
        "raw": location,
    }


def freshness_view(freshness: dict[str, Any] | None) -> dict[str, Any]:
    """Ubah freshness jadi baris berlabel, dengan ambang alert terpisah."""
    if not isinstance(freshness, dict):
        return {"rows": [], "alert": "", "raw": freshness}

    rows = []
    for key in FRESHNESS_ORDER:
        if key not in freshness:
            continue
        rows.append(
            {
                "key": key,
                "label": FRESHNESS_LABELS.get(key, key),
                "value": _scalar(freshness[key]),
            }
        )
    for key, value in freshness.items():
        if key in FRESHNESS_ORDER:
            continue
        rows.append(
            {
                "key": key,
                "label": FRESHNESS_LABELS.get(key, key.replace("_", " ").capitalize()),
                "value": _scalar(value),
            }
        )
    alert = freshness.get("alert_threshold")
    return {
        "rows": rows,
        "alert": alert if isinstance(alert, str) else "",
        "raw": freshness,
    }


def schema_rows(table: dict[str, Any]) -> list[dict[str, str]]:
    """Daftar kolom skema dengan tipe dan keterangan yang sudah dinormalkan."""
    rows = []
    for name, spec in (table.get("schema") or {}).items():
        if isinstance(spec, dict):
            type_name = spec.get("type") or ""
            description = spec.get("description") or "-"
        else:
            type_name = spec or ""
            description = "-"
        rows.append(
            {
                "name": name,
                "type": _scalar(type_name),
                "description": description,
            }
        )
    return rows


def catalog_summary(tables: list[dict[str, Any]]) -> dict[str, int]:
    installed = [table for table in tables if table.get("status") == "implemented"]
    return {
        "tables": len(tables),
        "implemented": len(installed),
        "planned": len(tables) - len(installed),
        "columns": sum(len(table.get("schema") or {}) for table in installed),
        "columns_all": sum(len(table.get("schema") or {}) for table in tables),
    }
