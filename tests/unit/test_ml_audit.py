from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from ml.audit import audit_cells, audit_context, main, render_markdown  # noqa: E402
from ml.province import load_provinces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVINCES_CSV = REPO_ROOT / "resources" / "indonesia_provinces.csv"


def test_audit_cells_summarizes_label_and_geography(cell_factory) -> None:
    frame = cell_factory(days=6, cells=2)
    provinces = load_provinces(PROVINCES_CSV)
    report = audit_cells(frame, provinces=provinces)

    assert report["rows"] == 12
    assert report["cells"] == 2
    assert report["dates"] == 6
    assert report["label"]["positive"] == 6
    assert report["label"]["negative"] == 6
    assert report["completeness"]["complete_rows"] == 12
    assert report["completeness"]["complete_dates"] == 6
    assert report["mixed_cell_days"] > 0
    assert report["date_range"]["dates"] == 6
    assert report["province_coverage"]["mapped_share"] == 1.0
    assert report["null_rates"]["frp_max"] == 0.0

    for value in report["univariate_auc"].values():
        assert value is None or 0.0 <= value <= 1.0


def test_audit_cells_counts_incomplete_rows(cell_factory) -> None:
    frame = cell_factory(days=4, cells=2)
    frame.loc[frame.index[:3], "label_complete"] = False
    report = audit_cells(frame)
    assert report["completeness"]["incomplete_rows"] == 3
    assert report["completeness"]["complete_dates"] == 3


def test_audit_context_marks_missing(weather_factory, air_quality_factory) -> None:
    missing = audit_context(None, None)
    assert missing["weather"]["status"] == "missing"
    assert missing["air_quality"]["status"] == "missing"

    present = audit_context(weather_factory(days=3), air_quality_factory(days=3))
    assert present["weather"]["status"] == "ok"
    assert present["weather"]["provinces"] == 1
    assert present["air_quality"]["rows"] == 12


def test_render_markdown_contains_expected_sections(cell_factory) -> None:
    provinces = load_provinces(PROVINCES_CSV)
    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "gold_cell_root": "data/gold/published/hotspot_cell_day",
        "cells": audit_cells(cell_factory(days=4), provinces=provinces),
        "context": audit_context(None, None),
    }
    markdown = render_markdown(report)
    assert "# Audit Data ML Sel-Hari" in markdown
    assert "| Positif |" in markdown
    assert "Kelengkapan label" in markdown
    assert "Laju positif harian" in markdown
    assert "Pemetaan provinsi" in markdown


def test_audit_cli_writes_json_and_markdown(cell_factory, tmp_path: Path) -> None:
    frame = cell_factory(days=6, cells=2)
    dataset_root = tmp_path / "gold" / "hotspot_cell_day"
    dataset_root.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        dataset_root / "part-0.parquet",
    )

    out_root = tmp_path / "audit"
    status = main(
        [
            "--gold-cell-root",
            str(dataset_root),
            "--out",
            str(out_root),
            "--provinces",
            str(PROVINCES_CSV),
            "--skip-context",
        ]
    )

    assert status == 0
    payload = json.loads((out_root / "ml_audit.json").read_text(encoding="utf-8"))
    assert payload["cells"]["rows"] == 12
    assert payload["cells"]["completeness"]["complete_rows"] == 12
    assert (out_root / "ml_audit.md").is_file()
