"""Batch 2A: MCD64A1 pixel observation infrastructure.

Modul ini hanya membangun inventory/status granule, required pixel-period,
pixel observation, dan reconciliation. Modul ini tidak menentukan primary scar,
tier, label, atau event evidence; itu tanggung jawab Batch 2B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from batch.silver.mcd64a1 import read_tile_bytes
from batch.silver.mcd64a1_coverage import doy_to_date, period_bounds
from common.config import Settings, load_dotenv
from common.storage import BronzeStore

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLISH_ROOT = REPO_ROOT / "data" / "silver" / "published"
DEFAULT_NORMALIZED_ROOT = REPO_ROOT / "data" / "silver" / "_normalized"

REQUIRED_ATTRS = {
    "BurnedCells",
    "MissingCells",
    "LandCells",
    "ValidLandCells",
    "ProductStartDay",
    "ProductEndDay",
    "year",
    "tile",
}
KEY_RE = re.compile(r"period=(?P<period>\d{4}-\d{2})/tile=(?P<tile>h\d{2}v\d{2})/(?P<file>[^/]+)$")
PRODUCTION_RE = re.compile(r"\.(\d{13})\.hdf$")

STATUS_ORDER = (
    "water",
    "missing",
    "unburned_special",
    "unburned",
    "burned",
    "unknown",
)


class PixelInfrastructureError(RuntimeError):
    """Batch 2A tidak dapat membangun tabel observasi."""


@dataclass(frozen=True)
class ManifestEntry:
    run_id: str
    month: str
    tile: str
    key: str
    sha256: str
    size_bytes: int
    granule_id: str


def _parse_key(key: str) -> tuple[str, str, str]:
    match = KEY_RE.search(key)
    if not match:
        raise PixelInfrastructureError(f"kunci HDF tidak dikenali: {key}")
    return match.group("period"), match.group("tile"), match.group("file")


def _production_datetime(filename: str) -> datetime | None:
    match = PRODUCTION_RE.search(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%j%H%M%S")
    except ValueError:
        return None


def _canonical_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def resolve_identity(
    producer_id: str | None,
    *,
    source_uri: str,
    file_hash: str | None,
) -> tuple[str | None, str]:
    """Identity utama atau fallback deterministic; tidak memakai nama file."""
    if producer_id:
        return producer_id, "producer_id"
    if file_hash:
        return hashlib.sha256(f"{source_uri}|{file_hash}".encode()).hexdigest(), "fallback"
    return None, "missing"


def _file_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _raster_hash(tile_data: Any) -> str:
    digest = hashlib.sha256()
    for name, array in (
        ("burn", tile_data.burn),
        ("qa", tile_data.qa),
        ("uncertainty", tile_data.uncertainty),
        ("first_day", tile_data.first_day),
        ("last_day", tile_data.last_day),
    ):
        value = np.ascontiguousarray(array)
        digest.update(name.encode("ascii"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(str(value.shape).encode("ascii"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _read_attributes(payload: bytes) -> dict[str, Any]:
    from pyhdf.SD import SD, SDC

    handle, path = tempfile.mkstemp(suffix=".hdf")
    os.close(handle)
    try:
        Path(path).write_bytes(payload)
        hdf = SD(path, SDC.READ)
        try:
            return dict(hdf.attributes())
        finally:
            hdf.end()
    finally:
        Path(path).unlink(missing_ok=True)


def _read_parquet_frame(root: Path) -> pd.DataFrame:
    if not root.exists():
        raise PixelInfrastructureError(f"folder parquet tidak ditemukan: {root}")
    dataset = ds.dataset(root, format="parquet", partitioning="hive")
    return dataset.to_table().to_pandas()


def _manifest_index(store: BronzeStore, prefix: str) -> dict[str, ManifestEntry]:
    index: dict[str, ManifestEntry] = {}
    manifest_keys = store.list_keys(f"{prefix}/manifests")
    for manifest_key in manifest_keys:
        payload = store.read_json(manifest_key)
        run_id = str(payload.get("run_id") or "")
        for entry in payload.get("entries", []):
            index[str(entry["key"])] = ManifestEntry(
                run_id=run_id,
                month=str(entry["month"]),
                tile=str(entry["tile"]),
                key=str(entry["key"]),
                sha256=str(entry["sha256"]),
                size_bytes=int(entry["size_bytes"]),
                granule_id=str(entry["granule_id"]),
            )
    return index


def _hotspot_mapping(publish_root: Path) -> pd.DataFrame:
    frame = _read_parquet_frame(publish_root / "firms" / "hotspot_label")
    needed = ["event_id", "date", "tile", "pixel_row", "pixel_col"]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise PixelInfrastructureError(f"hotspot_label kehilangan kolom: {missing}")
    frame = frame[needed].dropna(subset=["tile", "pixel_row", "pixel_col"]).copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["date"].notna()]
    frame["tile"] = frame["tile"].astype(str)
    frame["pixel_row"] = frame["pixel_row"].astype("int32")
    frame["pixel_col"] = frame["pixel_col"].astype("int32")
    return frame


def build_required(publish_root: Path) -> pd.DataFrame:
    """Bentuk required pixel-period dari window ±7 dan periode scar."""
    hotspots = _hotspot_mapping(publish_root)
    key_columns = ["tile", "pixel_row", "pixel_col"]

    base_parts: list[pd.DataFrame] = []
    for offset in (-7, 0, 7):
        part = hotspots[key_columns + ["event_id"]].copy()
        part["period"] = (hotspots["date"] + pd.Timedelta(days=offset)).dt.strftime("%Y-%m")
        base_parts.append(part)
    base = pd.concat(base_parts, ignore_index=True).drop_duplicates()
    base_counts = (
        base.groupby(key_columns + ["period"], as_index=False)
        .agg(n_events=("event_id", "nunique"))
        .assign(required_for_window=True, required_for_scar=False)
    )

    burn = _read_parquet_frame(publish_root / "mcd64a1" / "burn_scar")
    burn = burn[["tile", "pixel_row", "pixel_col", "burn_date"]].dropna().copy()
    burn["tile"] = burn["tile"].astype(str)
    burn["pixel_row"] = burn["pixel_row"].astype("int32")
    burn["pixel_col"] = burn["pixel_col"].astype("int32")
    burn["period"] = pd.to_datetime(burn["burn_date"], errors="coerce").dt.strftime("%Y-%m")
    burn = burn.dropna(subset=["period"])
    scar_periods = burn[key_columns + ["period"]].drop_duplicates()

    pixel_events = (
        hotspots[key_columns + ["event_id"]]
        .drop_duplicates()
        .groupby(key_columns, as_index=False)
        .agg(n_events=("event_id", "nunique"))
    )
    scar_required = scar_periods.merge(pixel_events, on=key_columns, how="left")
    scar_required["n_events"] = scar_required["n_events"].fillna(0).astype("int32")
    scar_required = scar_required.assign(
        required_for_window=False,
        required_for_scar=True,
    )

    combined = pd.concat([base_counts, scar_required], ignore_index=True)
    required = combined.groupby(key_columns + ["period"], as_index=False).agg(
        required_for_window=("required_for_window", "max"),
        required_for_scar=("required_for_scar", "max"),
        n_events=("n_events", "max"),
    )
    required["required_reason"] = np.where(
        required["required_for_window"] & required["required_for_scar"],
        "window+scar",
        np.where(required["required_for_window"], "window", "scar"),
    )
    required = required.sort_values(["tile", "pixel_row", "pixel_col", "period"]).reset_index(
        drop=True
    )
    if required.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any():
        raise PixelInfrastructureError("required pixel-period mengandung duplicate key")
    return required


def build_inventory(
    settings: Settings,
    store: BronzeStore,
    manifest_index: dict[str, ManifestEntry],
) -> pd.DataFrame:
    prefix = settings.burned_area.bronze_prefix
    keys = sorted(
        key
        for key in store.list_keys(f"{prefix}/dataset=burned_area")
        if key.lower().endswith(".hdf")
    )
    rows: list[dict[str, Any]] = []
    for key in keys:
        period, tile, filename = _parse_key(key)
        payload = store.read_bytes(key)
        file_hash = _file_hash(payload)
        manifest = manifest_index.get(key)
        read_status = "ok"
        failure_reason = None
        raster_hash = None
        metadata_complete = False
        attributes: dict[str, Any] = {}
        try:
            tile_data = read_tile_bytes(payload, tile=tile, month=period)
            raster_hash = _raster_hash(tile_data)
            attributes = _read_attributes(payload)
            metadata_complete = REQUIRED_ATTRS <= set(attributes)
        except Exception as exc:  # noqa: BLE001 - catat kegagalan per granule
            read_status = "error"
            failure_reason = f"{type(exc).__name__}: {exc}"

        producer_id = filename.removesuffix(".hdf")
        if not producer_id:
            producer_id = None
        identity, identity_source = resolve_identity(
            producer_id,
            source_uri=_canonical_uri(settings.garage.bucket, key),
            file_hash=file_hash,
        )

        manifest_match = (
            manifest is not None
            and manifest.sha256 == file_hash
            and manifest.size_bytes == len(payload)
        )
        rows.append(
            {
                "product": settings.burned_area.short_name,
                "product_version": settings.burned_area.version,
                "tile": tile,
                "period": period,
                "granule_id": producer_id,
                "granule_identity": identity,
                "identity_source": identity_source,
                "production_datetime": _production_datetime(filename),
                "canonical_source_uri": _canonical_uri(settings.garage.bucket, key),
                "source_file": key,
                "file_hash": file_hash,
                "manifest_sha256": manifest.sha256 if manifest else None,
                "manifest_size_bytes": manifest.size_bytes if manifest else None,
                "manifest_match": manifest_match,
                "raster_content_hash": raster_hash,
                "read_status": read_status,
                "metadata_complete": metadata_complete,
                "source_run_id": manifest.run_id if manifest else None,
                "failure_reason": failure_reason,
            }
        )
    if not rows:
        raise PixelInfrastructureError("tidak ada HDF MCD64A1 ditemukan")
    return (
        pd.DataFrame(rows)
        .sort_values(["tile", "period", "granule_identity"])
        .reset_index(drop=True)
    )


def build_status(inventory: pd.DataFrame, required: pd.DataFrame) -> pd.DataFrame:
    required_pairs = required[["tile", "period"]].drop_duplicates()
    pairs = pd.concat(
        [inventory[["tile", "period"]], required_pairs], ignore_index=True
    ).drop_duplicates()
    rows: list[dict[str, Any]] = []
    for tile, period in pairs.sort_values(["tile", "period"]).itertuples(index=False):
        candidates = inventory.loc[(inventory["tile"] == tile) & (inventory["period"] == period)]
        valid = candidates.loc[
            (candidates["read_status"] == "ok") & (candidates["metadata_complete"])
        ]
        hashes = valid["raster_content_hash"].dropna().unique().tolist()
        if candidates.empty:
            status = "missing"
            canonical = None
            raster_hash = None
            reason = "no granule candidate"
        elif valid.empty:
            status = "metadata_incomplete"
            canonical = None
            raster_hash = None
            reason = "no readable complete candidate"
        elif len(valid) == 1:
            status = "available" if len(candidates) == 1 else "unknown"
            canonical = valid.iloc[0]["granule_identity"]
            raster_hash = valid.iloc[0]["raster_content_hash"]
            reason = (
                "single readable candidate"
                if len(candidates) == 1
                else "additional candidate unreadable"
            )
        elif len(hashes) == 1:
            status = "identical_duplicate"
            canonical = valid.sort_values(["granule_identity"]).iloc[0]["granule_identity"]
            raster_hash = hashes[0]
            reason = "multiple readable candidates with identical raster"
        else:
            status = "conflict"
            canonical = None
            raster_hash = None
            reason = "multiple readable candidates with different raster"
        rows.append(
            {
                "tile": tile,
                "period": period,
                "source_status": status,
                "candidate_count": int(len(candidates)),
                "canonical_granule_identity": canonical,
                "raster_content_hash": raster_hash,
                "status_reason": reason,
            }
        )
    return pd.DataFrame(rows).sort_values(["tile", "period"]).reset_index(drop=True)


def _decode_raw_status(burn: np.ndarray, qa: np.ndarray) -> np.ndarray:
    land = (qa & 1) != 0
    valid = (qa & 2) != 0
    special = (qa >> 5) & 7
    result = np.full(len(burn), "unknown", dtype=object)
    result[(burn == 0) & valid & land & (special == 0)] = "unburned"
    result[(burn == 0) & valid & land & (special >= 1) & (special <= 5)] = "unburned_special"
    result[(burn == 0) & valid & land & (special >= 6)] = "unknown"
    result[(burn >= 1) & (burn <= 366) & valid & land] = "burned"
    # Precedence: water dan missing tetap eksplisit; QA invalid selain itu
    # adalah qa_insufficient, bukan missing granule.
    result[(burn == -2) | ~land] = "water"
    result[burn == -1] = "missing"
    result[(burn != -1) & (burn != -2) & ~valid & land] = "qa_insufficient"
    return result


def _coverage_dates(
    period: str,
    first_day: np.ndarray,
    last_day: np.ndarray,
) -> tuple[pd.Series, pd.Series]:
    year, _ = period.split("-")
    year = int(year)
    period_start, period_end = period_bounds(period)
    first_dates = pd.to_datetime(
        [doy_to_date(year, int(value)) if value not in (-1, -2) else None for value in first_day],
        errors="coerce",
    )
    last_dates = pd.to_datetime(
        [doy_to_date(year, int(value)) if value not in (-1, -2) else None for value in last_day],
        errors="coerce",
    )
    lower = pd.Timestamp(period_start)
    upper = pd.Timestamp(period_end)
    start = pd.Series(first_dates).clip(lower=lower, upper=upper)
    end = pd.Series(last_dates).clip(lower=lower, upper=upper)
    invalid = start.isna() | end.isna() | (start > end)
    start = start.where(~invalid)
    end = end.where(~invalid)
    return start, end


def build_observation(
    settings: Settings,
    store: BronzeStore,
    inventory: pd.DataFrame,
    status: pd.DataFrame,
    required: pd.DataFrame,
) -> pd.DataFrame:
    status_map = {(row.tile, row.period): row for row in status.itertuples(index=False)}
    inventory_by_key = {
        (row.tile, row.period, row.granule_identity): row
        for row in inventory.itertuples(index=False)
    }
    rows: list[pd.DataFrame] = []
    for (tile, period), group in required.groupby(["tile", "period"], sort=True):
        info = status_map.get((tile, period))
        if info is None or info.source_status not in {"available", "identical_duplicate"}:
            continue
        canonical = info.canonical_granule_identity
        inv = inventory_by_key.get((tile, period, canonical))
        if inv is None:
            continue
        payload = store.read_bytes(inv.source_file)
        tile_data = read_tile_bytes(payload, tile=tile, month=period)
        row_idx = group["pixel_row"].to_numpy(dtype=int)
        col_idx = group["pixel_col"].to_numpy(dtype=int)
        if (
            row_idx.min(initial=0) < 0
            or col_idx.min(initial=0) < 0
            or row_idx.max(initial=0) >= tile_data.burn.shape[0]
            or col_idx.max(initial=0) >= tile_data.burn.shape[1]
        ):
            raise PixelInfrastructureError(f"pixel di luar batas tile {tile} {period}")

        burn = tile_data.burn[row_idx, col_idx].astype("int16")
        qa = tile_data.qa[row_idx, col_idx].astype("int16")
        uncertainty = tile_data.uncertainty[row_idx, col_idx].astype("int16")
        first_day = tile_data.first_day[row_idx, col_idx].astype("int16")
        last_day = tile_data.last_day[row_idx, col_idx].astype("int16")
        raw_status = _decode_raw_status(burn, qa)
        raw_usable = np.isin(raw_status, ["burned", "unburned"])

        year = int(period.split("-")[0])
        burn_dates = pd.Series(pd.NaT, index=range(len(burn)), dtype="datetime64[ns]")
        burned = (burn >= 1) & (burn <= 366)
        if burned.any():
            burn_dates.loc[burned] = pd.to_datetime(
                [doy_to_date(year, int(value)) for value in burn[burned]]
            )
        coverage_start, coverage_end = _coverage_dates(period, first_day, last_day)

        part = group[
            [
                "tile",
                "pixel_row",
                "pixel_col",
                "period",
                "n_events",
                "required_for_window",
                "required_for_scar",
                "required_reason",
            ]
        ].copy()
        part["burn_date_code"] = burn
        part["burn_date"] = burn_dates.to_numpy()
        part["qa"] = qa
        part["qa_land"] = (qa & 1) != 0
        part["qa_valid"] = (qa & 2) != 0
        part["qa_shortened_period"] = (qa & 4) != 0
        part["qa_contextual_relabel"] = (qa & 8) != 0
        part["qa_special_condition"] = (qa >> 5) & 7
        part["uncertainty"] = uncertainty
        part["first_day"] = first_day
        part["last_day"] = last_day
        part["coverage_start_date"] = coverage_start.to_numpy()
        part["coverage_end_date"] = coverage_end.to_numpy()
        part["raw_pixel_status"] = raw_status
        part["raw_status_usable"] = raw_usable
        part["observation_available"] = True
        part["source_granule_identity"] = canonical
        part["source_content_hash"] = inv.raster_content_hash
        part["source_file"] = inv.source_file
        part["source_run_id"] = inv.source_run_id
        rows.append(part)

    if not rows:
        raise PixelInfrastructureError("tidak ada observation yang berhasil dibentuk")
    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values(["tile", "pixel_row", "pixel_col", "period"]).reset_index(drop=True)
    if result.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any():
        raise PixelInfrastructureError("observation mengandung duplicate key")
    return result


def build_reconciliation(
    required: pd.DataFrame,
    observation: pd.DataFrame,
    status: pd.DataFrame,
) -> pd.DataFrame:
    obs_cols = [
        "tile",
        "pixel_row",
        "pixel_col",
        "period",
        "observation_available",
        "raw_pixel_status",
        "raw_status_usable",
    ]
    obs = observation[obs_cols].copy()
    result = required.merge(
        obs,
        on=["tile", "pixel_row", "pixel_col", "period"],
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        status[["tile", "period", "source_status", "status_reason"]],
        on=["tile", "period"],
        how="left",
        validate="many_to_one",
    )
    observed = result["observation_available"].fillna(False)
    usable = result["raw_status_usable"].fillna(False)
    result["reconciliation_category"] = np.select(
        [
            observed & usable,
            observed & ~usable,
            result["source_status"].eq("conflict"),
            result["source_status"].eq("missing"),
            result["source_status"].eq("metadata_incomplete"),
            result["source_status"].eq("unknown"),
            result["source_status"].isin(["available", "identical_duplicate"]),
        ],
        [
            "observed_usable",
            "observed_unusable",
            "granule_conflict",
            "missing_granule",
            "metadata_incomplete",
            "source_unknown",
            "extraction_error",
        ],
        default="other_explained",
    )
    result["reconciliation_reason"] = np.where(
        observed,
        result["raw_pixel_status"].fillna("unknown"),
        result["status_reason"].fillna("no status"),
    )
    required_keys = set(
        map(tuple, required[["tile", "pixel_row", "pixel_col", "period"]].to_numpy())
    )
    observation_keys = set(
        map(tuple, observation[["tile", "pixel_row", "pixel_col", "period"]].to_numpy())
    )
    unexpected = observation_keys - required_keys
    if unexpected:
        raise PixelInfrastructureError(f"unexpected observation: {len(unexpected)} key")
    if result.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any():
        raise PixelInfrastructureError("reconciliation mengandung duplicate required key")
    return result.sort_values(["tile", "pixel_row", "pixel_col", "period"]).reset_index(drop=True)


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.rmtree(path.parent) if path.is_dir() else path.unlink()
    frame.to_parquet(path, index=False)


def build_all(
    settings: Settings,
    *,
    publish_root: Path,
    normalized_root: Path,
) -> dict[str, Any]:
    store = BronzeStore(settings.garage)
    prefix = settings.burned_area.bronze_prefix
    manifest_index = _manifest_index(store, prefix)
    required = build_required(publish_root)
    inventory = build_inventory(settings, store, manifest_index)
    status = build_status(inventory, required)
    observation = build_observation(settings, store, inventory, status, required)
    reconciliation = build_reconciliation(required, observation, status)
    category_counts = reconciliation["reconciliation_category"].value_counts().to_dict()
    expected = len(required)
    actual = int(sum(category_counts.values()))
    if actual != expected:
        raise PixelInfrastructureError(f"reconciliation sum {actual} != required {expected}")
    outputs = {
        "granule_inventory": inventory,
        "granule_status": status,
        "pixel_period_required": required,
        "pixel_observation": observation,
        "pixel_period_reconciliation": reconciliation,
    }
    for name, frame in outputs.items():
        folder = normalized_root / "mcd64a1" / f"dataset={name}"
        folder.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(folder / "part-00000.parquet", index=False)
    return {
        "required": len(required),
        "inventory": len(inventory),
        "status": status["source_status"].value_counts().to_dict(),
        "observation": len(observation),
        "reconciliation": category_counts,
        "required_sum": actual,
    }


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Build Batch 2A pixel observation infrastructure")
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=Path(os.getenv("SILVER_PUBLISH_ROOT", str(DEFAULT_PUBLISH_ROOT))),
    )
    parser.add_argument(
        "--normalized-root",
        type=Path,
        default=Path(os.getenv("SILVER_NORMALIZED_ROOT", str(DEFAULT_NORMALIZED_ROOT))),
    )
    args = parser.parse_args(argv)
    result = build_all(
        settings,
        publish_root=args.publish_root,
        normalized_root=args.normalized_root,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PixelInfrastructureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
