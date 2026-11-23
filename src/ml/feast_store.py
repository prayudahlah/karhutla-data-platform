"""Operasi Feast: apply definisi, materialize online store, dan inspeksi.

Dipakai flow Prefect dan CLI. Import ``feast`` dilakukan di dalam fungsi supaya
modul ML lain tidak ikut memuat Feast saat hanya butuh training dari Gold.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from common.config import load_dotenv
from ml.config import FEATURE_SERVICE, MLSettings


class FeastError(RuntimeError):
    """Feast tidak bisa dimuat atau dijalankan."""


def _load_definitions(settings: MLSettings) -> ModuleType:
    path = settings.feast_repo / "definitions.py"
    if not path.is_file():
        raise FeastError(f"Definisi Feast tidak ditemukan: {path}")
    spec = importlib.util.spec_from_file_location("karhutla_feast_definitions", path)
    if spec is None or spec.loader is None:
        raise FeastError(f"Tidak bisa memuat definisi Feast: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_feature_store(settings: MLSettings | None = None):
    """Buka FeatureStore dari ``feature_repo``."""
    settings = settings or MLSettings.from_env()
    if not (settings.feast_repo / "feature_store.yaml").is_file():
        raise FeastError(
            f"feature_store.yaml tidak ditemukan di {settings.feast_repo}; "
            "jalankan dari root repo atau set FEAST_REPO_PATH"
        )
    try:
        from feast import FeatureStore
    except ImportError as exc:  # pragma: no cover - extra feast belum dipasang
        raise FeastError(
            "Feast belum terpasang. Jalankan: pip install -e '.[feast]'"
        ) from exc
    settings.feast_registry.parent.mkdir(parents=True, exist_ok=True)
    settings.feast_online_store.parent.mkdir(parents=True, exist_ok=True)
    return FeatureStore(repo_path=str(settings.feast_repo))


def apply_feature_definitions(settings: MLSettings | None = None) -> dict[str, Any]:
    """Daftarkan entity, feature view, dan feature service ke registry."""
    settings = settings or MLSettings.from_env()
    store = get_feature_store(settings)
    definitions = _load_definitions(settings)
    objects = definitions.get_objects()
    store.apply(objects)
    return {
        "project": store.project,
        "objects": [type(item).__name__ for item in objects],
        "feature_service": FEATURE_SERVICE,
        "registry": str(settings.feast_registry),
        "registry_hash": registry_hash(settings),
    }


def materialize_features(
    settings: MLSettings | None = None,
    *,
    end_date: datetime | None = None,
) -> dict[str, Any]:
    """Muat nilai fitur terbaru ke online store (SQLite lokal)."""
    settings = settings or MLSettings.from_env()
    store = get_feature_store(settings)
    end = end_date or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    store.materialize_incremental(end_date=end)
    return {
        "materialized_until": end.isoformat(),
        "online_store": str(settings.feast_online_store),
        "registry_hash": registry_hash(settings),
    }


def registry_hash(settings: MLSettings | None = None) -> str | None:
    """SHA-256 registry Feast; ``None`` bila registry belum ada."""
    settings = settings or MLSettings.from_env()
    path = settings.feast_registry
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe_feature_service(settings: MLSettings | None = None) -> dict[str, Any]:
    """Ringkas feature service untuk log dan dokumentasi."""
    settings = settings or MLSettings.from_env()
    store = get_feature_store(settings)
    service = store.get_feature_service(settings.feature_service)
    projections = getattr(service, "feature_view_projections", None)
    if projections is None:
        projections = getattr(service, "features", [])
    views: dict[str, list[str]] = {}
    for projection in projections:
        name = getattr(projection, "name", None) or "unknown"
        views[str(name)] = [field.name for field in projection.features]
    return {
        "feature_service": settings.feature_service,
        "feature_views": views,
        "registry_hash": registry_hash(settings),
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    settings = MLSettings.from_env()
    parser = argparse.ArgumentParser(description="Operasi Feast untuk fitur temporal")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("apply", help="daftarkan definisi ke registry")
    materialize = sub.add_parser("materialize", help="muat fitur ke online store")
    materialize.add_argument(
        "--end-date",
        default=None,
        help="ISO-8601, default sekarang (UTC)",
    )
    sub.add_parser("describe", help="tampilkan feature service")
    args = parser.parse_args(argv)

    try:
        if args.command == "apply":
            result = apply_feature_definitions(settings)
        elif args.command == "materialize":
            end = datetime.fromisoformat(args.end_date) if args.end_date else None
            result = materialize_features(settings, end_date=end)
        else:
            result = describe_feature_service(settings)
    except FeastError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
