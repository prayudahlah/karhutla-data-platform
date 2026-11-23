"""Halaman portal: katalog, lineage, dan ringkasan.

Semua rute read-only dan tidak memanggil database. Kalau ``catalog.json`` belum
dihasilkan, halaman tetap 200 dan menampilkan perintah yang harus dijalankan,
bukan error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from serving.portal.catalog import (
    catalog_summary,
    freshness_view,
    location_view,
    schema_rows,
)
from serving.portal.graph import build_graph
from serving.portal.loader import PortalData

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _pretty(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


templates.env.filters["pretty"] = _pretty

router = APIRouter(tags=["portal"])


def _portal(request: Request) -> PortalData:
    return request.app.state.portal


def _render(
    request: Request,
    template: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
):
    """Render dengan identitas SSO dari header proxy."""
    settings = request.app.state.settings
    auth_url = (settings.auth_url or "").rstrip("/")
    user = request.headers.get("Remote-User", "")
    groups = request.headers.get("Remote-Groups", "")
    role = "admin" if "admin" in groups else ("viewer" if user else "")
    services = [
        {"name": name, "url": url, "note": note}
        for name, url, note in (
            ("Grafana", settings.grafana_url, "Metrik dan log operasional"),
            ("Metabase", settings.metabase_url, "Dashboard mart Gold"),
            ("Prefect", settings.prefect_url, "Jadwal dan riwayat job"),
        )
        if url
    ]
    dashboard_url = (
        settings.metabase_dashboard_url
        or settings.metabase_url
        or "/dashboard"
    )
    payload = {
        "user": user,
        "role": role,
        "dashboard_url": dashboard_url,
        "services": services,
        "auth_url": auth_url,
        "logout_url": f"{auth_url}/logout?rd=/" if auth_url and user else "",
        **context,
    }
    return templates.TemplateResponse(
        request, template, payload, status_code=status_code
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    """Dashboard Gold yang membaca API serving dari browser."""
    return _render(
        request,
        "dashboard.html",
        {"active": "", "catalog_root": _portal(request).root},
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    portal = _portal(request)
    catalog = portal.catalog
    lineage = portal.lineage
    return _render(
        request,
        "index.html",
        {
            "active": "ringkasan",
            "catalog": catalog,
            "lineage": lineage,
            "tables": portal.tables,
            "catalog_root": portal.root,
        },
    )


@router.get("/catalog", response_class=HTMLResponse)
def catalog_page(request: Request) -> HTMLResponse:
    portal = _portal(request)
    tables = portal.tables
    column_max = max(
        [len(table.get("schema") or {}) for table in tables], default=0
    )
    return _render(
        request,
        "catalog.html",
        {
            "active": "katalog",
            "catalog": portal.catalog,
            "tables": tables,
            "table_names": {str(table.get("name")) for table in tables},
            "summary": catalog_summary(tables),
            "column_max": column_max or 1,
            "catalog_root": portal.root,
        },
    )


@router.get("/catalog/{name}", response_class=HTMLResponse)
def dataset_page(request: Request, name: str) -> HTMLResponse:
    portal = _portal(request)
    table = portal.table(name)
    if table is None:
        raise HTTPException(status_code=404, detail=f"Dataset tidak ditemukan: {name}")
    return _render(
        request,
        "dataset.html",
        {
            "active": "katalog",
            "catalog": portal.catalog,
            "table": table,
            "table_names": {str(item.get("name")) for item in portal.tables},
            "location": location_view(table.get("location")),
            "freshness": freshness_view(table.get("freshness")),
            "columns": schema_rows(table),
            "catalog_root": portal.root,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    """Halaman khusus admin.

    Akses dijaga Caddy dan Authelia. Halaman ini hanya menampilkan identitas
    yang dikirim proxy, supaya uji 403 bisa dibedakan dari 404.
    """
    return _render(
        request,
        "admin.html",
        {
            "active": "admin",
            "user": request.headers.get("Remote-User", ""),
            "groups": request.headers.get("Remote-Groups", ""),
        },
    )


@router.get("/lineage", response_class=HTMLResponse)
def lineage_page(request: Request, focus: str | None = None) -> HTMLResponse:
    portal = _portal(request)
    lineage = portal.lineage
    graph = build_graph(
        lineage, {str(table.get("name")) for table in portal.tables}, focus
    )
    return _render(
        request,
        "lineage.html",
        {
            "active": "lineage",
            "lineage": lineage,
            "graph": graph,
            "catalog_root": portal.root,
        },
    )
