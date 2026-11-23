"""Baca catalog.json dan lineage.json hasil ``batch.gold.catalog``.

Portal sengaja tidak menulis apa pun. Semua data berasal dari berkas yang
dihasilkan job Gold, sehingga halaman selalu mencerminkan hasil build terakhir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    """Kembalikan isi JSON, atau None kalau belum ada atau rusak."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class PortalData:
    """Akses berkas katalog dan lineage di satu folder."""

    root: Path

    @property
    def catalog(self) -> dict[str, Any] | None:
        return load_json(self.root / "catalog.json")

    @property
    def lineage(self) -> dict[str, Any] | None:
        return load_json(self.root / "lineage.json")

    @property
    def tables(self) -> list[dict[str, Any]]:
        catalog = self.catalog or {}
        tables = catalog.get("tables") or []
        return [table for table in tables if isinstance(table, dict)]

    def table(self, name: str) -> dict[str, Any] | None:
        for table in self.tables:
            if table.get("name") == name:
                return table
        return None

    def nodes_by_layer(self) -> dict[str, list[dict[str, Any]]]:
        lineage = self.lineage or {}
        nodes = lineage.get("nodes") or []
        grouped: dict[str, list[dict[str, Any]]] = {
            "bronze": [],
            "silver": [],
            "gold": [],
        }
        for node in nodes:
            if not isinstance(node, dict):
                continue
            grouped.setdefault(str(node.get("layer", "lain")), []).append(node)
        return grouped
