"""Audit dataset Gold ``hotspot_cell_day`` sebelum training.

Menghasilkan ringkasan yang menjawab pertanyaan praktis:

- berapa sel, tanggal, dan sel-hari yang dipakai;
- bagaimana distribusi label biner dan kelengkapan jendela label;
- berapa banyak sel-hari campuran (positif dan negatif dalam satu sel);
- berapa besar sinyal ``n_hotspot`` sendirian sebagai baseline kebocoran;
- berapa persen sel yang bisa dipetakan ke provinsi;
- apakah cuaca/AQ tersedia untuk periode yang sama.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.config import load_dotenv
from common.run import utc_now_iso
from ml.config import MLSettings
from ml.dataset import DatasetError, load_cell_day, read_parquet_dataset
from ml.province import (
    DEFAULT_PROVINCES_CSV,
    Province,
    assign_nearest_province,
    load_provinces,
)

CELL_NULL_COLUMNS = (
    "frp_max",
    "frp_mean",
    "frp_p95",
    "brightness_max",
    "brightness_diff_max",
    "confidence_max",
    "confidence_mean",
    "scan_max",
    "track_max",
    "hour_of_max_frp",
    "center_lat",
    "center_lon",
)

UNIVARIATE_COLUMNS = ("n_hotspot", "frp_max", "frp_mean")


def _null_rates(frame: pd.DataFrame, columns: Sequence[str]) -> dict[str, float | None]:
    return {
        column: (None if column not in frame.columns else float(frame[column].isna().mean()))
        for column in columns
    }


def _value_counts(series: pd.Series, limit: int = 10) -> dict[str, int]:
    counts = series.dropna().astype(str).value_counts().head(limit)
    return {str(key): int(value) for key, value in counts.items()}


def _date_range(values: pd.Series) -> dict[str, Any]:
    parsed = pd.to_datetime(values, errors="coerce").dropna()
    if parsed.empty:
        return {"start": None, "end": None, "dates": 0, "span_days": 0}
    start = parsed.min().date()
    end = parsed.max().date()
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dates": int(parsed.dt.date.nunique()),
        "span_days": (end - start).days + 1,
    }


def _auc(score: pd.Series, target: pd.Series) -> float | None:
    """AUC rank-based tanpa dependensi scikit-learn."""
    values = pd.to_numeric(score, errors="coerce")
    mask = values.notna() & target.notna()
    if mask.sum() < 2:
        return None
    y = target[mask].to_numpy(dtype=int)
    positives = int(y.sum())
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(values[mask].to_numpy(dtype=float), kind="mergesort")
    ranks = np.empty(len(y), dtype=float)
    ranks[order] = np.arange(1, len(y) + 1)
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def _province_coverage(
    frame: pd.DataFrame,
    provinces: Sequence[Province],
) -> dict[str, Any]:
    matches = assign_nearest_province(
        frame["center_lat"].to_numpy(dtype=float),
        frame["center_lon"].to_numpy(dtype=float),
        provinces,
    )
    mapped = matches.province != None  # noqa: E711 - numpy object array
    distances = matches.distance_km[np.isfinite(matches.distance_km)]
    quantiles = (
        {f"p{int(q * 100)}": float(np.quantile(distances, q)) for q in (0.5, 0.9, 0.99)}
        if distances.size
        else {"p50": None, "p90": None, "p99": None}
    )
    return {
        "mapped_rows": int(mapped.sum()),
        "mapped_share": float(mapped.mean()) if len(mapped) else 0.0,
        "distance_km": {
            **quantiles,
            "max": float(distances.max()) if distances.size else None,
            "share_over_150_km": float((distances > 150).mean()) if distances.size else None,
            "share_over_300_km": float((distances > 300).mean()) if distances.size else None,
        },
        "top_provinces": _value_counts(pd.Series(matches.province, dtype="object")),
    }


def audit_cells(
    frame: pd.DataFrame,
    *,
    provinces: Sequence[Province] | None = None,
) -> dict[str, Any]:
    """Ringkas tabel Gold sel-hari tanpa mengubah isinya."""
    total = len(frame)
    if total == 0:
        raise DatasetError("Tabel sel kosong")

    missing = {"label", "label_complete", "cell_id", "date"} - set(frame.columns)
    if missing:
        raise DatasetError(f"Tabel sel tidak memiliki kolom: {', '.join(sorted(missing))}")

    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    label = pd.to_numeric(frame["label"], errors="coerce")
    complete = frame["label_complete"].astype("boolean").fillna(False).astype(bool)
    complete_frame = frame.loc[complete]
    complete_label = label.loc[complete]
    complete_dates = dates.loc[complete]

    positives = int((label == 1).sum())
    negatives = int((label == 0).sum())
    density = pd.to_numeric(frame["n_hotspot"], errors="coerce").dropna()
    quantiles = (
        {f"p{int(q * 100)}": float(np.quantile(density, q)) for q in (0.5, 0.9, 0.99)}
        if len(density)
        else {"p50": None, "p90": None, "p99": None}
    )

    mixed = None
    if {"audit_n_confirmed", "n_hotspot"} <= set(frame.columns):
        confirmed = pd.to_numeric(frame["audit_n_confirmed"], errors="coerce")
        hot = pd.to_numeric(frame["n_hotspot"], errors="coerce")
        mixed = int(((confirmed > 0) & (confirmed < hot)).sum())

    per_day = (
        complete_frame.assign(_label=complete_label)
        .groupby(complete_dates, dropna=True)["_label"]
        .agg(["count", "sum", "mean"])
        .sort_index()
    )

    report: dict[str, Any] = {
        "rows": total,
        "cells": int(frame["cell_id"].nunique()),
        "dates": int(dates.nunique()),
        "date_range": _date_range(dates),
        "label": {
            "positive": positives,
            "negative": negatives,
            "positive_share": float(positives / total) if total else 0.0,
        },
        "completeness": {
            "complete_rows": int(complete.sum()),
            "complete_share": float(complete.mean()),
            "incomplete_rows": int((~complete).sum()),
            "complete_dates": int(complete_dates.nunique()),
            "complete_range": _date_range(complete_dates),
        },
        "density": {
            "mean": float(density.mean()) if len(density) else None,
            **quantiles,
            "max": float(density.max()) if len(density) else None,
        },
        "mixed_cell_days": mixed,
        "univariate_auc": {
            column: _auc(complete_frame[column], complete_label)
            if column in complete_frame.columns
            else None
            for column in UNIVARIATE_COLUMNS
        },
        "per_day": {
            day.date().isoformat(): {
                "rows": int(row["count"]),
                "positive": int(row["sum"]),
                "positive_share": float(row["mean"]),
            }
            for day, row in per_day.iterrows()
        },
        "null_rates": _null_rates(frame, CELL_NULL_COLUMNS),
    }

    if provinces is not None and not complete_frame.empty:
        report["province_coverage"] = _province_coverage(complete_frame, provinces)
    return report


def audit_context(
    weather: pd.DataFrame | None,
    air_quality: pd.DataFrame | None,
) -> dict[str, Any]:
    """Ringkas ketersediaan cuaca/AQ; tidak gagal bila salah satu kosong."""

    def summarize(
        frame: pd.DataFrame | None,
        null_columns: Sequence[str],
    ) -> dict[str, Any]:
        if frame is None or frame.empty:
            return {"status": "missing", "rows": 0}
        date_column = "date" if "date" in frame.columns else None
        return {
            "status": "ok",
            "rows": len(frame),
            "date_range": _date_range(frame[date_column]) if date_column else None,
            "provinces": int(frame["province"].nunique()) if "province" in frame else None,
            "null_rates": _null_rates(frame, null_columns),
        }

    weather_columns = (
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "wind_speed_10m",
        "soil_moisture_0_to_7cm",
        "vapour_pressure_deficit",
        "et0_fao_evapotranspiration",
    )
    air_columns = ("pm2_5", "pm10", "carbon_monoxide", "aerosol_optical_depth")
    return {
        "weather": summarize(weather, weather_columns),
        "air_quality": summarize(air_quality, air_columns),
    }


def render_markdown(report: dict[str, Any]) -> str:
    cells = report["cells"]
    label = cells["label"]
    completeness = cells["completeness"]
    context = report["context"]

    lines = [
        "# Audit Data ML Sel-Hari",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Gold root: `{report.get('gold_cell_root', '-')}`",
        "",
        "## Ringkasan",
        "",
        "| Metrik | Nilai |",
        "|---|---|",
        f"| Sel-hari | {cells['rows']} |",
        f"| Sel unik | {cells['cells']} |",
        f"| Tanggal | {cells['dates']} |",
    ]
    if cells.get("date_range"):
        date_range = cells["date_range"]
        lines.append(
            f"| Rentang tanggal | {date_range['start']} s.d. {date_range['end']} |"
        )
    lines.extend(
        [
            f"| Positif | {label['positive']} ({label['positive_share']:.1%}) |",
            f"| Negatif | {label['negative']} |",
            f"| Sel-hari campuran | {cells.get('mixed_cell_days', '-')} |",
            "",
            "## Kelengkapan label",
            "",
            f"- Baris dengan jendela scar lengkap: {completeness['complete_rows']} "
            f"({completeness['complete_share']:.1%})",
            f"- Baris tidak lengkap: {completeness['incomplete_rows']}",
            f"- Tanggal lengkap: {completeness['complete_dates']}",
        ]
    )
    complete_range = completeness.get("complete_range") or {}
    if complete_range.get("start"):
        lines.append(
            f"- Rentang lengkap: {complete_range['start']} s.d. {complete_range['end']}"
        )

    lines.extend(
        [
            "",
            "## Sinyal univariat (baris lengkap)",
            "",
            "| Fitur | AUC |",
            "|---|---:|",
        ]
    )
    for column, value in cells["univariate_auc"].items():
        lines.append(f"| {column} | {'-' if value is None else f'{value:.3f}'} |")

    lines.extend(
        [
            "",
            "## Laju positif harian (baris lengkap)",
            "",
            "| Tanggal | Baris | Positif | Porsi |",
            "|---|---:|---:|---:|",
        ]
    )
    for day, item in list(cells.get("per_day", {}).items()):
        lines.append(
            f"| {day} | {item['rows']} | {item['positive']} "
            f"| {item['positive_share']:.1%} |"
        )

    density = cells.get("density", {})

    def _num(value: Any) -> str:
        return "-" if value is None else f"{value:.1f}"

    lines.extend(
        [
            "",
            "## Kepadatan deteksi",
            "",
            f"- Rata-rata hotspot per sel-hari: {_num(density.get('mean'))}",
            f"- Median: {_num(density.get('p50'))}",
            f"- P90: {_num(density.get('p90'))}",
            f"- P99: {_num(density.get('p99'))}",
            f"- Maksimum: {_num(density.get('max'))}",
        ]
    )

    lines.extend(["", "## Nilai kosong", "", "| Kolom | Null rate |", "|---|---:|"])
    for column, rate in cells["null_rates"].items():
        lines.append(f"| {column} | {'-' if rate is None else f'{rate:.1%}'} |")

    coverage = cells.get("province_coverage")
    if coverage:
        distance = coverage["distance_km"]

        def _km(value: Any) -> str:
            return "-" if value is None else f"{value:.1f} km"

        def _share(value: Any) -> str:
            return "-" if value is None else f"{value:.1%}"

        lines.extend(
            [
                "",
                "## Pemetaan provinsi",
                "",
                f"- Sel terpetakan: {coverage['mapped_rows']} ({coverage['mapped_share']:.1%})",
                f"- Median jarak ke ibu kota: {_km(distance['p50'])}",
                f"- P90 jarak: {_km(distance['p90'])}",
                f"- P99 jarak: {_km(distance['p99'])}",
                f"- Jarak > 150 km: {_share(distance['share_over_150_km'])}",
                f"- Jarak > 300 km: {_share(distance['share_over_300_km'])}",
            ]
        )

    lines.extend(
        [
            "",
            "## Konteks cuaca dan AQ",
            "",
            "| Dataset | Status | Baris | Hari | Provinsi |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for name in ("weather", "air_quality"):
        item = context[name]
        date_range = item.get("date_range") or {}
        lines.append(
            f"| {name} | {item['status']} | {item.get('rows', 0)} | "
            f"{date_range.get('dates', '-')} | {item.get('provinces', '-')} |"
        )

    lines.append("")
    return "\n".join(lines)


def _read_optional(path: Path, label: str) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = read_parquet_dataset(path)
    except DatasetError as exc:
        print(f"PERINGATAN: {label} dilewati: {exc}", file=sys.stderr)
        return None
    return frame


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    settings = MLSettings.from_env()

    parser = argparse.ArgumentParser(description="Audit dataset ML Gold sel-hari")
    parser.add_argument(
        "--gold-cell-root",
        default=str(settings.gold_cell_root),
        help="akar parquet Gold hotspot_cell_day (default: ML_GOLD_CELL_ROOT)",
    )
    parser.add_argument(
        "--silver-root",
        default=str(settings.silver_root),
        help="akar Silver published untuk konteks cuaca/AQ",
    )
    parser.add_argument(
        "--out",
        default=str(settings.audit_root),
        help="folder keluaran audit",
    )
    parser.add_argument(
        "--provinces",
        default=str(DEFAULT_PROVINCES_CSV),
        help="CSV referensi ibu kota provinsi",
    )
    parser.add_argument(
        "--skip-context",
        action="store_true",
        help="jangan baca cuaca/AQ",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="ikutkan baris yang jendela labelnya belum lengkap",
    )
    args = parser.parse_args(argv)

    gold_cell_root = Path(args.gold_cell_root)
    silver_root = Path(args.silver_root)
    out_root = Path(args.out)

    try:
        provinces = load_provinces(Path(args.provinces))
        cells = load_cell_day(gold_cell_root, require_complete=not args.include_incomplete)
        cells_report = audit_cells(cells, provinces=provinces)
    except (DatasetError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.skip_context:
        context_report = {"weather": {"status": "skipped"}, "air_quality": {"status": "skipped"}}
    else:
        weather = _read_optional(silver_root / "open_meteo" / "weather", "weather")
        air_quality = _read_optional(silver_root / "open_meteo" / "air_quality", "air_quality")
        context_report = audit_context(weather, air_quality)

    report = {
        "generated_at": utc_now_iso(),
        "gold_cell_root": str(gold_cell_root),
        "silver_root": str(silver_root),
        "cells": cells_report,
        "context": context_report,
    }

    out_root.mkdir(parents=True, exist_ok=True)
    json_path = out_root / "ml_audit.json"
    markdown_path = out_root / "ml_audit.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "rows": cells_report["rows"],
                "date_range": cells_report.get("date_range"),
                "label": cells_report["label"],
                "complete_dates": cells_report["completeness"]["complete_dates"],
                "univariate_auc": cells_report["univariate_auc"],
                "json": str(json_path),
                "markdown": str(markdown_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
