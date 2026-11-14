"""Normalisasi MCD64A1: HDF di Bronze menjadi Parquet di Silver.

Bronze menyimpan granule HDF apa adanya. Modul ini membongkar formatnya menjadi
satu baris per piksel terbakar, lengkap dengan koordinat titik tengah piksel.

Yang dihasilkan:

- ``silver/_normalized/mcd64a1/dataset=burn_scar/date=<burn_date>/``
  Baris piksel terbakar. Partisi memakai tanggal terbakar, bukan tanggal unduh,
  supaya cocok dengan join per tanggal di lapisan berikutnya.
- ``silver/_normalized/mcd64a1/dataset=tiles/date=<awal periode>/``
  Grid sinusoidal tiap tile. Dipakai untuk memetakan hotspot ke baris dan kolom.
- ``silver/_normalized/mcd64a1/dataset=coverage/date=<awal periode>/``
  Daftar tile dan periode yang sudah diurai, supaya nilai kosong bisa
  dibedakan antara "tidak terbakar" dan "belum diunduh".
- ``silver/_dq/mcd64a1/dataset=burn_scar/run_id=<run_id>.json``
  Laporan kualitas satu kali jalan.

Pemetaan nama: di Bronze datasetnya ``burned_area`` (nama produk), di Silver
menjadi ``burn_scar`` (nama tabel). Kunci Bronze tetap seperti yang sudah
tertulis, jadi tidak perlu unduh ulang.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from batch.silver.dq import DQReport, check_not_null, check_row_count, write_quarantine
from batch.silver.parquet import ObjectStore, table_from_rows, upload_parquet
from batch.silver.paths import dq_report_key, normalized_key, quarantine_key
from common.config import BurnedAreaSettings

SOURCE = "mcd64a1"
BRONZE_DATASET = "burned_area"
SCAR_DATASET = "burn_scar"
TILES_DATASET = "tiles"
COVERAGE_DATASET = "coverage"

# Radius bola pada proyeksi sinusoidal MODIS, dalam meter.
EARTH_RADIUS_M = 6371007.181

BURN_DATE_LAYER = "Burn Date"
QA_LAYER = "QA"
UNCERTAINTY_LAYER = "Burn Date Uncertainty"
FIRST_DAY_LAYER = "First Day"
LAST_DAY_LAYER = "Last Day"

SCAR_SCHEMA = pa.schema(
    [
        ("tile", pa.string()),
        ("row", pa.int32()),
        ("col", pa.int32()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("burn_date", pa.date32()),
        ("burn_month", pa.string()),
        ("burn_doy", pa.int16()),
        ("qa", pa.uint8()),
        ("uncertainty", pa.uint8()),
        ("first_day", pa.int16()),
        ("last_day", pa.int16()),
        ("in_bbox", pa.bool_()),
        ("source_file", pa.string()),
    ]
)

TILE_SCHEMA = pa.schema(
    [
        ("tile", pa.string()),
        ("period", pa.string()),
        ("ulx", pa.float64()),
        ("uly", pa.float64()),
        ("px", pa.float64()),
        ("py", pa.float64()),
        ("nx", pa.int32()),
        ("ny", pa.int32()),
    ]
)

COVERAGE_SCHEMA = pa.schema(
    [
        ("period", pa.string()),
        ("tile", pa.string()),
        ("source_file", pa.string()),
        ("run_id", pa.string()),
        ("pixels_burned", pa.int64()),
        ("pixels_outside_month", pa.int64()),
        ("ingested_at", pa.string()),
    ]
)

REJECT_OUTSIDE_MONTH = "burn_date_outside_month"


class Mcd64a1SilverError(RuntimeError):
    """Granule tidak bisa diurai, atau Bronze untuk periode itu kosong."""


@dataclass(frozen=True)
class TileGrid:
    ulx: float
    uly: float
    px: float
    py: float
    nx: int
    ny: int

    @property
    def x_max(self) -> float:
        return self.ulx + self.px * self.nx

    @property
    def y_min(self) -> float:
        return self.uly - self.py * self.ny


@dataclass(frozen=True)
class TileData:
    tile: str
    month: str
    grid: TileGrid
    burn: np.ndarray
    qa: np.ndarray
    uncertainty: np.ndarray
    first_day: np.ndarray
    last_day: np.ndarray


@dataclass(frozen=True)
class TileParseResult:
    scar_rows: list[dict[str, Any]]
    rejected_rows: list[dict[str, Any]]
    tile_row: dict[str, Any]
    coverage_row: dict[str, Any]


def parse_month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise Mcd64a1SilverError(f"Periode harus berbentuk YYYY-MM, bukan {value!r}") from exc


def month_doy_range(month: str) -> tuple[int, int]:
    """Hari pertama dan terakhir bulan itu dalam penomoran hari setahun."""
    start = parse_month(month)
    next_month = (
        date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    )
    return start.timetuple().tm_yday, next_month.timetuple().tm_yday - 1


def burn_date_from_doy(month: str, day_of_year: int) -> date:
    """Tanggal kalender dari periode granule dan hari ke berapa dalam setahun."""
    start = parse_month(month)
    resolved = date(start.year, 1, 1) + timedelta(days=int(day_of_year) - 1)
    if (resolved.year, resolved.month) != (start.year, start.month):
        raise Mcd64a1SilverError(f"burn date {day_of_year} tidak berada di periode {month}")
    return resolved


_CORNER = re.compile(r"(UpperLeftPointMtrs|LowerRightMtrs)=\(([^)]+)\)")
_TILE = re.compile(r"tile=(h\d{2}v\d{2})")


def parse_struct_metadata(metadata: str, *, nx: int, ny: int) -> TileGrid:
    """Ambil sudut grid dari StructMetadata.0 milik HDF-EOS2."""
    corners: dict[str, tuple[float, float]] = {}
    for name, raw in _CORNER.findall(metadata):
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 2:
            raise Mcd64a1SilverError(f"{name} tidak berisi dua angka: {raw!r}")
        corners[name] = (float(parts[0]), float(parts[1]))

    missing = {"UpperLeftPointMtrs", "LowerRightMtrs"} - corners.keys()
    if missing:
        raise Mcd64a1SilverError("StructMetadata tidak memuat " + ", ".join(sorted(missing)))

    ulx, uly = corners["UpperLeftPointMtrs"]
    lrx, lry = corners["LowerRightMtrs"]
    px = (lrx - ulx) / nx
    py = (uly - lry) / ny
    if px <= 0 or py <= 0:
        raise Mcd64a1SilverError(f"Ukuran piksel tidak masuk akal: px={px}, py={py}")
    return TileGrid(ulx=ulx, uly=uly, px=px, py=py, nx=nx, ny=ny)


def pixel_centers(
    grid: TileGrid, rows: np.ndarray, cols: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Koordinat sinusoidal titik tengah piksel."""
    x = grid.ulx + grid.px * (cols + 0.5)
    y = grid.uly - grid.py * (rows + 0.5)
    return x, y


def sinusoidal_to_latlon(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    latitude = np.degrees(y / EARTH_RADIUS_M)
    longitude = np.degrees(x / (EARTH_RADIUS_M * np.cos(np.radians(latitude))))
    return latitude, longitude


def in_bbox(latitude: float, longitude: float, bbox: tuple[float, ...]) -> bool:
    west, south, east, north = bbox
    return west <= longitude <= east and south <= latitude <= north


def tile_from_key(key: str) -> str:
    match = _TILE.search(key)
    if not match:
        raise Mcd64a1SilverError(f"Kunci Bronze tidak memuat tile=: {key}")
    return match.group(1)


def read_tile(path: Path, *, tile: str, month: str) -> TileData:
    """Baca HDF4 dengan pyhdf. Butuh berkas di disk, bukan bytes."""
    try:
        from pyhdf.SD import SD, SDC
    except ImportError as exc:  # pragma: no cover - tergantung environment
        raise Mcd64a1SilverError("pyhdf belum terpasang; jalankan pip install -e .") from exc

    try:
        handle = SD(str(path), SDC.READ)
    except Exception as exc:  # noqa: BLE001 - pyhdf melempar tipe sendiri
        raise Mcd64a1SilverError(f"Tidak bisa membuka {path}: {exc}") from exc

    try:
        burn = handle.select(BURN_DATE_LAYER)[:]
        qa = handle.select(QA_LAYER)[:]
        uncertainty = handle.select(UNCERTAINTY_LAYER)[:]
        first_day = handle.select(FIRST_DAY_LAYER)[:]
        last_day = handle.select(LAST_DAY_LAYER)[:]
        metadata = handle.attributes().get("StructMetadata.0", "")
    finally:
        handle.end()

    if not metadata:
        raise Mcd64a1SilverError(f"{path} tidak punya StructMetadata.0")

    grid = parse_struct_metadata(metadata, nx=int(burn.shape[1]), ny=int(burn.shape[0]))
    return TileData(
        tile=tile,
        month=month,
        grid=grid,
        burn=burn,
        qa=qa,
        uncertainty=uncertainty,
        first_day=first_day,
        last_day=last_day,
    )


def read_tile_bytes(payload: bytes, *, tile: str, month: str) -> TileData:
    """pyhdf hanya bisa membaca dari path, jadi bytes ditulis ke berkas sementara."""
    handle, path = tempfile.mkstemp(suffix=".hdf")
    try:
        with os.fdopen(handle, "wb") as file_handle:
            file_handle.write(payload)
        return read_tile(Path(path), tile=tile, month=month)
    finally:
        Path(path).unlink(missing_ok=True)


def parse_tile(
    data: TileData,
    *,
    bbox: tuple[float, ...],
    source_file: str,
    run_id: str,
) -> TileParseResult:
    """Ubah satu tile menjadi baris scar, baris karantina, dan metadata grid."""
    burn = data.burn
    first_doy, last_doy = month_doy_range(data.month)
    inside = (burn >= first_doy) & (burn <= last_doy)
    outside = (burn > 0) & ~inside

    rows, cols = np.nonzero(inside)
    scar_rows: list[dict[str, Any]] = []
    if rows.size:
        x, y = pixel_centers(data.grid, rows, cols)
        latitude, longitude = sinusoidal_to_latlon(x, y)
        for index in range(rows.size):
            row_index = int(rows[index])
            col_index = int(cols[index])
            doy = int(burn[row_index, col_index])
            lat = float(latitude[index])
            lon = float(longitude[index])
            scar_rows.append(
                {
                    "tile": data.tile,
                    "row": row_index,
                    "col": col_index,
                    "latitude": lat,
                    "longitude": lon,
                    "burn_date": burn_date_from_doy(data.month, doy),
                    "burn_month": data.month,
                    "burn_doy": doy,
                    "qa": int(data.qa[row_index, col_index]),
                    "uncertainty": int(data.uncertainty[row_index, col_index]),
                    "first_day": int(data.first_day[row_index, col_index]),
                    "last_day": int(data.last_day[row_index, col_index]),
                    "in_bbox": in_bbox(lat, lon, bbox),
                    "source_file": source_file,
                }
            )

    rejected_rows = [
        {
            "tile": data.tile,
            "row": int(row_index),
            "col": int(col_index),
            "burn_doy": int(burn[row_index, col_index]),
            "burn_month": data.month,
        }
        for row_index, col_index in zip(*np.nonzero(outside), strict=True)
    ]

    grid = data.grid
    tile_row = {
        "tile": data.tile,
        "period": data.month,
        "ulx": grid.ulx,
        "uly": grid.uly,
        "px": grid.px,
        "py": grid.py,
        "nx": grid.nx,
        "ny": grid.ny,
    }
    coverage_row = {
        "period": data.month,
        "tile": data.tile,
        "source_file": source_file,
        "run_id": run_id,
        "pixels_burned": len(scar_rows),
        "pixels_outside_month": len(rejected_rows),
        "ingested_at": "",
    }
    return TileParseResult(
        scar_rows=scar_rows,
        rejected_rows=rejected_rows,
        tile_row=tile_row,
        coverage_row=coverage_row,
    )


def normalize_month(
    store: ObjectStore,
    settings: BurnedAreaSettings,
    *,
    month: str,
    run_id: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Urai semua tile satu periode dari Bronze menjadi Parquet Silver."""
    start = parse_month(month)
    bronze_prefix = f"{settings.bronze_prefix}/dataset={BRONZE_DATASET}/period={month}"
    keys = sorted(key for key in store.list_keys(bronze_prefix) if key.endswith(".hdf"))
    if not keys:
        raise Mcd64a1SilverError(
            f"Tidak ada granule di {bronze_prefix}; jalankan burned-fetch dulu"
        )

    scar_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    rejected: list[dict[str, Any]] = []
    tile_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    outside_month_total = 0

    for key in keys:
        tile = tile_from_key(key)
        data = read_tile_bytes(store.read_bytes(key), tile=tile, month=month)
        result = parse_tile(data, bbox=settings.bbox, source_file=key, run_id=run_id)
        for row in result.scar_rows:
            scar_by_date[row["burn_date"]].append(row)
        rejected.extend(result.rejected_rows)
        outside_month_total += len(result.rejected_rows)
        tile_rows.append(result.tile_row)
        coverage_rows.append(result.coverage_row)

    written = 0
    for burn_day in sorted(scar_by_date):
        rows = scar_by_date[burn_day]
        upload_parquet(
            store,
            normalized_key(SOURCE, SCAR_DATASET, burn_day),
            table_from_rows(rows, schema=SCAR_SCHEMA),
            metadata={"run-id": run_id, "source": SOURCE, "dataset": SCAR_DATASET},
            overwrite=overwrite,
        )
        written += len(rows)

    upload_parquet(
        store,
        normalized_key(SOURCE, TILES_DATASET, start),
        table_from_rows(tile_rows, schema=TILE_SCHEMA),
        metadata={"run-id": run_id, "source": SOURCE, "dataset": TILES_DATASET},
        overwrite=overwrite,
    )
    upload_parquet(
        store,
        normalized_key(SOURCE, COVERAGE_DATASET, start),
        table_from_rows(coverage_rows, schema=COVERAGE_SCHEMA),
        metadata={"run-id": run_id, "source": SOURCE, "dataset": COVERAGE_DATASET},
        overwrite=overwrite,
    )

    if rejected:
        write_quarantine(
            store,
            quarantine_key(SOURCE, SCAR_DATASET, start),
            rejected,
            source=SOURCE,
            dataset=SCAR_DATASET,
            reason=REJECT_OUTSIDE_MONTH,
            run_id=run_id,
            overwrite=overwrite,
        )

    report = DQReport(source=SOURCE, dataset=SCAR_DATASET, run_id=run_id)
    report.input_rows = written + outside_month_total
    report.accepted_rows = written
    report.rejected_rows = outside_month_total
    report.duplicate_rows = _duplicate_rows(scar_by_date)
    report.add_check(
        "scar_rows_written",
        passed=report.input_rows == report.accepted_rows + report.rejected_rows,
        input_rows=report.input_rows,
        accepted_rows=report.accepted_rows,
        rejected_rows=report.rejected_rows,
    )
    report.checks.append(check_row_count("tiles_read", actual=len(tile_rows), expected=len(keys)))
    # Sedikit piksel di luar periode bisa muncul dari tile yang menyentuh bulan
    # tetangga. Ambang 5% dipakai supaya anomali besar tetap terlihat.
    outside_ratio = outside_month_total / report.input_rows if report.input_rows else 0.0
    report.add_check(
        "pixels_outside_month",
        passed=outside_ratio <= 0.05,
        pixels=outside_month_total,
        input_rows=report.input_rows,
        ratio=round(outside_ratio, 4),
    )
    report.checks.append(
        check_not_null(
            "scar_keys_not_null",
            [row for rows in scar_by_date.values() for row in rows],
            ["burn_date", "latitude", "longitude", "tile"],
        )
    )
    dq_key = dq_report_key(SOURCE, SCAR_DATASET, run_id)
    report.write(store, dq_key, overwrite=overwrite)

    return {
        "month": month,
        "tiles": len(tile_rows),
        "scar_rows": written,
        "quarantined_rows": outside_month_total,
        "dq_report_key": dq_key,
        "dq_status": report.status,
    }


def _duplicate_rows(scar_by_date: dict[date, list[dict[str, Any]]]) -> int:
    """Hitung piksel ganda; satu tile hanya boleh menyumbang satu baris per piksel."""
    keys = [(row["tile"], row["row"], row["col"]) for rows in scar_by_date.values() for row in rows]
    counts = Counter(keys)
    return sum(count - 1 for count in counts.values() if count > 1)
