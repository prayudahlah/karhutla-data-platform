"""Batch 2B: event-level Burn Scar evidence and label reconciliation.

Modul ini memakai output Batch 2A. Ia tidak mengubah Burn Scar source,
`hotspot_scar_label`, Gold lama, loader, fitur, split, atau model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from batch.silver.mcd64a1_coverage import (
    coverage_interval,
    doy_to_date,
    period_bounds,
)
from common.config import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLISH_ROOT = REPO_ROOT / "data" / "silver" / "published"
DEFAULT_NORMALIZED_ROOT = REPO_ROOT / "data" / "silver" / "_normalized"
LABEL_RULE_VERSION = "phase01-temporal-label-v1"

REASON_PRIORITY = (
    "source_conflict",
    "source_missing",
    "metadata_incomplete",
    "observation_missing",
    "candidate_insufficient",
    "candidate_invalid_without_valid_primary",
    "raw_missing",
    "raw_water",
    "raw_qa_insufficient",
    "raw_unburned_special",
    "raw_unknown",
    "window_partial",
    "window_unknown",
    "required_evidence_incomplete",
)
REASON_RANK = {reason: rank for rank, reason in enumerate(REASON_PRIORITY)}


class EventEvidenceError(RuntimeError):
    """Batch 2B tidak dapat membangun event evidence."""


@dataclass(frozen=True)
class ScarValidation:
    status: str
    reason: str | None


def burn_scar_key(tile: str, pixel_row: int, pixel_col: int, burn_date: date) -> str:
    return f"{tile}|{int(pixel_row)}|{int(pixel_col)}|{burn_date.isoformat()}"


def tier_for_gap(gap_days: float | int | None) -> str | None:
    """Tier kontrak untuk primary gap; None jika tidak ada primary."""
    if gap_days is None or pd.isna(gap_days):
        return None
    if gap_days <= 3:
        return "strong"
    if gap_days <= 7:
        return "medium"
    if gap_days <= 14:
        return "weak"
    return "candidate"


def _read_parquet(root: Path) -> pd.DataFrame:
    if not root.exists():
        raise EventEvidenceError(f"parquet tidak ditemukan: {root}")
    return ds.dataset(root, format="parquet", partitioning="hive").to_table().to_pandas()


def _events(publish_root: Path) -> pd.DataFrame:
    frame = _read_parquet(publish_root / "firms" / "hotspot_label")
    columns = ["event_id", "date", "tile", "pixel_row", "pixel_col", "latitude", "longitude"]
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise EventEvidenceError(f"hotspot_label kehilangan kolom: {missing}")
    frame = (
        frame[columns]
        .dropna(subset=["tile", "pixel_row", "pixel_col", "latitude", "longitude"])
        .copy()
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["date"].notna()]
    frame["tile"] = frame["tile"].astype(str)
    frame["pixel_row"] = frame["pixel_row"].astype("int32")
    frame["pixel_col"] = frame["pixel_col"].astype("int32")
    frame["cell_y"] = np.floor(frame["latitude"] / 0.25).astype("int32")
    frame["cell_x"] = np.floor(frame["longitude"] / 0.25).astype("int32")
    frame["cell_id"] = frame["cell_y"].astype(str) + "_" + frame["cell_x"].astype(str)
    return frame.reset_index(drop=True)


def _scars(publish_root: Path) -> pd.DataFrame:
    frame = _read_parquet(publish_root / "mcd64a1" / "burn_scar")
    frame = frame[["tile", "pixel_row", "pixel_col", "burn_date"]].dropna().copy()
    frame["tile"] = frame["tile"].astype(str)
    frame["pixel_row"] = frame["pixel_row"].astype("int32")
    frame["pixel_col"] = frame["pixel_col"].astype("int32")
    frame["burn_date"] = pd.to_datetime(frame["burn_date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["burn_date"]).drop_duplicates()
    frame["burn_scar_key"] = [
        burn_scar_key(tile, row, col, burn_date)
        for tile, row, col, burn_date in frame[
            ["tile", "pixel_row", "pixel_col", "burn_date"]
        ].itertuples(index=False)
    ]
    return frame.reset_index(drop=True)


def _pixel_observation(batch_root: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(batch_root / f"dataset={name}" / "part-00000.parquet")


def validate_scar_date(
    scar_date: date,
    *,
    period: str,
    source_status: str,
    observation_available: bool,
    raw_pixel_status: str | None,
    qa_land: bool | None,
    qa_valid: bool | None,
    qa_special_condition: int | None,
    burn_date_code: int | None,
    first_day: int | None,
    last_day: int | None,
) -> ScarValidation:
    """Validasi satu scar date; tidak memutuskan label event."""
    if source_status not in {"available", "identical_duplicate"}:
        reason = {
            "missing": "source_missing",
            "conflict": "source_conflict",
            "metadata_incomplete": "metadata_incomplete",
        }.get(source_status, "unknown")
        return ScarValidation("insufficient", reason)
    if not observation_available:
        return ScarValidation("insufficient", "observation_missing")
    if raw_pixel_status in {"missing", "unknown"}:
        return ScarValidation("insufficient", "observation_unusable")
    if raw_pixel_status == "water" or not bool(qa_land):
        return ScarValidation("invalid", "not_land")
    if raw_pixel_status == "qa_insufficient" or not bool(qa_valid):
        return ScarValidation("invalid", "qa_invalid")
    if raw_pixel_status == "unburned_special" or (qa_special_condition or 0) > 0:
        return ScarValidation("invalid", "qa_invalid")
    if raw_pixel_status != "burned":
        return ScarValidation("invalid", "not_burned")
    if burn_date_code is None or not 1 <= int(burn_date_code) <= 366:
        return ScarValidation("invalid", "not_burned")
    year = int(period.split("-")[0])
    burn_date = doy_to_date(year, int(burn_date_code))
    if burn_date is None or burn_date != scar_date:
        return ScarValidation("invalid", "burn_date_mismatch")
    interval = coverage_interval(period, first_day, last_day)
    if interval is None:
        return ScarValidation("insufficient", "first_last_not_cover")
    if not (interval[0] <= scar_date <= interval[1]):
        return ScarValidation("invalid", "first_last_not_cover")
    return ScarValidation("valid", None)


def _required_periods(events: pd.DataFrame, scars: pd.DataFrame) -> pd.DataFrame:
    base_parts: list[pd.DataFrame] = []
    for offset in (-7, 0, 7):
        part = events[["event_id", "tile", "pixel_row", "pixel_col"]].copy()
        part["period"] = (events["date"] + pd.Timedelta(days=offset)).dt.strftime("%Y-%m")
        part["window_flag"] = True
        base_parts.append(part)
    base = pd.concat(base_parts, ignore_index=True).drop_duplicates(["event_id", "period"])
    scar = events[["event_id", "tile", "pixel_row", "pixel_col"]].merge(
        scars[["tile", "pixel_row", "pixel_col", "burn_date"]],
        on=["tile", "pixel_row", "pixel_col"],
        how="inner",
    )
    scar["period"] = pd.to_datetime(scar["burn_date"]).dt.strftime("%Y-%m")
    scar["window_flag"] = False
    scar = scar[
        ["event_id", "tile", "pixel_row", "pixel_col", "period", "window_flag"]
    ].drop_duplicates(["event_id", "period"])
    combined = pd.concat([base, scar], ignore_index=True)
    required = combined.groupby(
        ["event_id", "tile", "pixel_row", "pixel_col", "period"], as_index=False
    ).agg(window_flag=("window_flag", "max"))
    scar_keys = set(map(tuple, scar[["event_id", "period"]].to_numpy()))
    required["scar_flag"] = [
        (event_id, period) in scar_keys
        for event_id, period in required[["event_id", "period"]].itertuples(index=False)
    ]
    required["required_reason"] = np.select(
        [required["window_flag"] & required["scar_flag"], required["window_flag"]],
        ["window+scar", "window"],
        default="scar_candidate",
    )
    return required.reset_index(drop=True)


def _candidate_frame(
    events: pd.DataFrame,
    scars: pd.DataFrame,
    required: pd.DataFrame,
    observation: pd.DataFrame,
    status: pd.DataFrame,
) -> pd.DataFrame:
    candidates = events[["event_id", "date", "tile", "pixel_row", "pixel_col"]].merge(
        scars[["tile", "pixel_row", "pixel_col", "burn_date", "burn_scar_key"]],
        on=["tile", "pixel_row", "pixel_col"],
        how="inner",
    )
    candidates["period"] = pd.to_datetime(candidates["burn_date"]).dt.strftime("%Y-%m")
    candidates["gap_days"] = (
        (pd.to_datetime(candidates["burn_date"]).dt.normalize() - candidates["date"])
        .dt.days.abs()
        .astype("int32")
    )
    obs_cols = [
        "tile",
        "pixel_row",
        "pixel_col",
        "period",
        "observation_available",
        "raw_pixel_status",
        "qa_land",
        "qa_valid",
        "qa_special_condition",
        "burn_date_code",
        "first_day",
        "last_day",
    ]
    candidates = candidates.merge(
        observation[obs_cols],
        on=["tile", "pixel_row", "pixel_col", "period"],
        how="left",
        validate="many_to_one",
    )
    candidates = candidates.merge(
        status[["tile", "period", "source_status"]],
        on=["tile", "period"],
        how="left",
        validate="many_to_one",
    )
    candidates["source_status"] = candidates["source_status"].fillna("missing")
    candidates["observation_available"] = candidates["observation_available"].fillna(False)
    candidates["period"] = candidates["period"].astype(str)
    validations: list[ScarValidation] = []
    for row in candidates.itertuples(index=False):
        validations.append(
            validate_scar_date(
                row.burn_date,
                period=row.period,
                source_status=row.source_status,
                observation_available=bool(row.observation_available),
                raw_pixel_status=row.raw_pixel_status,
                qa_land=row.qa_land,
                qa_valid=row.qa_valid,
                qa_special_condition=row.qa_special_condition,
                burn_date_code=row.burn_date_code,
                first_day=row.first_day,
                last_day=row.last_day,
            )
        )
    candidates["validation_status"] = [item.status for item in validations]
    candidates["rejection_reason"] = [item.reason for item in validations]
    candidates["is_primary"] = False
    candidates["match_rank"] = pd.NA
    candidates["tie_count"] = 0

    valid = candidates.loc[candidates["validation_status"] == "valid"].copy()
    if not valid.empty:
        valid = valid.sort_values(["event_id", "gap_days", "burn_date", "burn_scar_key"])
        valid["match_rank"] = valid.groupby("event_id").cumcount() + 1
        valid["tie_count"] = valid.groupby("event_id")["gap_days"].transform(
            lambda values: (values == values.min()).sum()
        )
        primary = valid.loc[valid["match_rank"] == 1].copy().set_index("event_id")
        rank_map = valid.set_index(["event_id", "burn_scar_key"])["match_rank"]
        tie_map = valid.groupby("event_id")["tie_count"].first()
        candidates["match_rank"] = [
            rank_map.get((event_id, key), pd.NA)
            for event_id, key in candidates[["event_id", "burn_scar_key"]].itertuples(index=False)
        ]
        candidates["tie_count"] = candidates["event_id"].map(tie_map).fillna(0).astype("int32")
        candidates["is_primary"] = (
            candidates["event_id"].map(primary["burn_scar_key"]).eq(candidates["burn_scar_key"])
        )
    return candidates.sort_values(
        ["event_id", "gap_days", "burn_date", "burn_scar_key"]
    ).reset_index(drop=True)


def _window_status(
    events: pd.DataFrame,
    required_obs: pd.DataFrame,
) -> pd.Series:
    """Hitung status window per event secara vectorized dari interval First/Last.

    Helper validate_window_coverage tetap menjadi kontrak; implementasi ini
    menguji segment per periode untuk menghindari loop 483k event.
    """
    frame = required_obs.merge(events[["event_id", "date"]], on="event_id", how="left")
    period_bounds_map = {
        period: period_bounds(period) for period in frame["period"].dropna().unique()
    }
    frame["period_start"] = frame["period"].map(
        lambda value: pd.Timestamp(period_bounds_map[value][0])
    )
    frame["period_end"] = frame["period"].map(
        lambda value: pd.Timestamp(period_bounds_map[value][1])
    )
    frame["segment_start"] = np.maximum(frame["period_start"], frame["date"] - pd.Timedelta(days=7))
    frame["segment_end"] = np.minimum(frame["period_end"], frame["date"] + pd.Timedelta(days=7))
    frame["covered"] = (
        frame["coverage_start_date"].notna()
        & frame["coverage_end_date"].notna()
        & frame["coverage_start_date"].le(frame["segment_start"])
        & frame["coverage_end_date"].ge(frame["segment_end"])
        & frame["source_status"].isin(["available", "identical_duplicate"])
        & frame["observation_available"].astype(bool)
    )
    grouped = frame.groupby("event_id")["covered"]
    all_covered = grouped.all()
    any_covered = grouped.any()
    result = pd.Series("unknown", index=all_covered.index, dtype=object)
    result.loc[any_covered] = "partial"
    result.loc[all_covered] = "full"
    return result


def _reason_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for reason in REASON_PRIORITY:
        mask = frame[reason].fillna(False).astype(bool)
        if mask.any():
            rows.append(frame.loc[mask, ["event_id"]].assign(reason_code=reason))
    if not rows:
        return pd.DataFrame(columns=["event_id", "reason_code", "reason_rank", "is_primary_reason"])
    result = pd.concat(rows, ignore_index=True)
    result["reason_rank"] = result["reason_code"].map(REASON_RANK)
    best = result.groupby("event_id")["reason_rank"].transform("min")
    result["is_primary_reason"] = result["reason_rank"] == best
    return result


def _burned_without_scar_candidate(
    required_obs: pd.DataFrame,
    scars: pd.DataFrame,
) -> pd.Series:
    """Burned usable observation tanpa scar pada pixel/tanggal yang sama."""
    code = pd.to_numeric(required_obs["burn_date_code"], errors="coerce")
    years = pd.to_numeric(required_obs["period"].astype(str).str.slice(0, 4), errors="coerce")
    burn_dates = [
        doy_to_date(int(year), int(day)) if pd.notna(year) and pd.notna(day) else None
        for year, day in zip(years, code, strict=True)
    ]
    lookup = required_obs[["tile", "pixel_row", "pixel_col"]].copy()
    lookup["burn_date"] = burn_dates
    scar_keys = (
        scars[["tile", "pixel_row", "pixel_col", "burn_date"]]
        .drop_duplicates()
        .assign(_has_scar=True)
    )
    lookup = lookup.merge(
        scar_keys,
        on=["tile", "pixel_row", "pixel_col", "burn_date"],
        how="left",
        validate="many_to_one",
    )
    burned_usable = (
        required_obs["source_status"].isin(["available", "identical_duplicate"])
        & required_obs["observation_available"].eq(True)
        & required_obs["raw_status_usable"].eq(True)
        & required_obs["raw_pixel_status"].eq("burned")
        & code.between(1, 366)
        & pd.to_datetime(lookup["burn_date"], errors="coerce").notna()
    )
    result = burned_usable & lookup["_has_scar"].isna()
    result.index = required_obs.index
    return result


def _fingerprint(frame: pd.DataFrame) -> pd.Series:
    def one(row: Any) -> str:
        values = [
            str(row.cell_id),
            pd.Timestamp(row.date).date().isoformat(),
            "" if pd.isna(row.label) else str(int(row.label)),
            str(row.label_status),
            "true" if bool(row.label_complete) else "false",
            str(row.label_reason),
        ]
        return hashlib.sha256(
            "|".join("<NULL>" if value == "" else value for value in values).encode()
        ).hexdigest()

    return frame.apply(one, axis=1)


def build_all(
    *,
    publish_root: Path,
    batch_root: Path,
    normalized_root: Path,
) -> dict[str, Any]:
    events = _events(publish_root)
    scars = _scars(publish_root)
    observation = _pixel_observation(batch_root, "pixel_observation")
    status = _pixel_observation(batch_root, "granule_status")
    required = _required_periods(events, scars)
    required_obs = required.merge(
        observation[
            [
                "tile",
                "pixel_row",
                "pixel_col",
                "period",
                "observation_available",
                "raw_pixel_status",
                "raw_status_usable",
                "qa_land",
                "qa_valid",
                "qa_special_condition",
                "burn_date_code",
                "first_day",
                "last_day",
                "coverage_start_date",
                "coverage_end_date",
                "source_granule_identity",
                "source_content_hash",
                "source_file",
                "source_run_id",
            ]
        ],
        on=["tile", "pixel_row", "pixel_col", "period"],
        how="left",
    ).merge(
        status[["tile", "period", "source_status"]],
        on=["tile", "period"],
        how="left",
    )
    required_obs["source_status"] = required_obs["source_status"].fillna("missing")
    required_obs["observation_available"] = required_obs["observation_available"].fillna(False)
    required_obs["_burned_without_scar_candidate"] = _burned_without_scar_candidate(
        required_obs, scars
    )

    candidates = _candidate_frame(events, scars, required, observation, status)
    # Aggregate required evidence completeness.
    required_obs["_source_bad"] = ~required_obs["source_status"].isin(
        ["available", "identical_duplicate"]
    )
    required_obs["_obs_missing"] = ~required_obs["observation_available"].astype(bool)
    required_obs["_raw_unusable"] = ~required_obs["raw_status_usable"].fillna(False).astype(bool)
    required_obs["_raw_missing"] = required_obs["raw_pixel_status"].eq("missing")
    required_obs["_raw_water"] = required_obs["raw_pixel_status"].eq("water")
    required_obs["_raw_qa"] = required_obs["raw_pixel_status"].eq("qa_insufficient")
    required_obs["_raw_special"] = required_obs["raw_pixel_status"].eq("unburned_special")
    required_obs["_raw_unknown"] = required_obs["raw_pixel_status"].eq("unknown")
    agg = required_obs.groupby("event_id", as_index=False).agg(
        required_period_count=("period", "nunique"),
        missing_observation_count=("_obs_missing", "sum"),
        raw_unusable_count=("_raw_unusable", "sum"),
        source_missing=("source_status", lambda s: s.eq("missing").any()),
        source_conflict=("source_status", lambda s: s.eq("conflict").any()),
        metadata_incomplete=("source_status", lambda s: s.eq("metadata_incomplete").any()),
        raw_missing=("_raw_missing", "any"),
        raw_water=("_raw_water", "any"),
        raw_qa_insufficient=("_raw_qa", "any"),
        raw_unburned_special=("_raw_special", "any"),
        raw_unknown=("_raw_unknown", "any"),
        burned_without_scar_candidate=("_burned_without_scar_candidate", "any"),
    )
    required_window = required[required["window_flag"]]
    window_status = _window_status(
        events,
        required_obs.merge(
            required_window[["event_id", "period"]],
            on=["event_id", "period"],
            how="inner",
        ),
    )

    cand_counts = candidates.groupby("event_id", as_index=False).agg(
        n_candidate_scars=("burn_scar_key", "nunique"),
        n_valid_candidates=("validation_status", lambda s: s.eq("valid").sum()),
        n_rejected_candidates=("validation_status", lambda s: s.eq("invalid").sum()),
        n_insufficient_candidates=("validation_status", lambda s: s.eq("insufficient").sum()),
    )
    primary = candidates[candidates["is_primary"]].copy()
    primary = primary[
        ["event_id", "burn_scar_key", "burn_date", "gap_days", "match_rank", "tie_count"]
    ]
    evidence = (
        events.merge(agg, on="event_id", how="left")
        .merge(cand_counts, on="event_id", how="left")
        .merge(
            primary.rename(
                columns={
                    "burn_scar_key": "primary_burn_scar_key",
                    "burn_date": "primary_burn_date",
                    "gap_days": "primary_gap_days",
                    "match_rank": "primary_match_rank",
                    "tie_count": "primary_tie_count",
                }
            ),
            on="event_id",
            how="left",
        )
    )
    for column in [
        "n_candidate_scars",
        "n_valid_candidates",
        "n_rejected_candidates",
        "n_insufficient_candidates",
    ]:
        evidence[column] = evidence[column].fillna(0).astype("int32")
    evidence["window_coverage_status"] = evidence["event_id"].map(window_status).fillna("unknown")
    evidence["candidate_insufficient"] = evidence["n_insufficient_candidates"] > 0
    evidence["candidate_invalid_without_valid_primary"] = (evidence["n_valid_candidates"] == 0) & (
        evidence["n_rejected_candidates"] > 0
    )
    evidence["burned_without_scar_candidate"] = (
        evidence["burned_without_scar_candidate"].fillna(False).astype(bool)
    )
    evidence["required_evidence_incomplete"] = (
        (evidence["missing_observation_count"].fillna(0) > 0)
        | evidence["burned_without_scar_candidate"]
    )
    evidence["source_bad"] = (
        evidence["source_missing"] | evidence["source_conflict"] | evidence["metadata_incomplete"]
    )
    incomplete = (
        evidence["source_bad"]
        | (evidence["missing_observation_count"].fillna(0) > 0)
        | (evidence["raw_unusable_count"].fillna(0) > 0)
        | evidence["candidate_insufficient"]
        | evidence["candidate_invalid_without_valid_primary"]
        | evidence["burned_without_scar_candidate"]
    )
    evidence["evidence_status"] = np.select(
        [incomplete, evidence["window_coverage_status"].ne("full")],
        ["incomplete", "insufficient"],
        default="valid",
    )
    evidence["primary_tier"] = np.select(
        [
            evidence["primary_gap_days"].isna(),
            evidence["primary_gap_days"] <= 3,
            evidence["primary_gap_days"] <= 7,
            evidence["primary_gap_days"] <= 14,
        ],
        [None, "strong", "medium", "weak"],
        default="candidate",
    )
    valid_evidence = evidence["evidence_status"].eq("valid").astype(bool)
    evidence["candidate_reason"] = np.where(
        valid_evidence,
        np.select(
            [
                evidence["primary_gap_days"].gt(14),
                evidence["n_candidate_scars"].eq(0),
            ],
            ["scar_outside_window", "no_scar_match"],
            default=None,
        ),
        None,
    )
    evidence["label"] = np.select(
        [
            evidence["evidence_status"].ne("valid"),
            (evidence["evidence_status"] == "valid") & evidence["primary_gap_days"].le(7),
            (evidence["evidence_status"] == "valid") & (evidence["n_candidate_scars"] == 0),
        ],
        [None, 1, 0],
        default=0,
    )
    evidence["label"] = pd.array(evidence["label"], dtype="Int8")
    evidence["label_status"] = np.where(
        evidence["evidence_status"].ne("valid"),
        "incomplete",
        np.where(evidence["label"].eq(1).fillna(False), "positive", "negative"),
    )
    evidence["label_complete"] = evidence["label_status"].ne("incomplete")
    reason_frame = evidence.assign(
        **{
            "source_missing": evidence["source_missing"].fillna(False),
            "source_conflict": evidence["source_conflict"].fillna(False),
            "metadata_incomplete": evidence["metadata_incomplete"].fillna(False),
            "observation_missing": evidence["missing_observation_count"].fillna(0) > 0,
            "candidate_insufficient": evidence["candidate_insufficient"],
            "candidate_invalid_without_valid_primary": evidence[
                "candidate_invalid_without_valid_primary"
            ],
            "raw_missing": evidence["raw_missing"].fillna(False),
            "raw_water": evidence["raw_water"].fillna(False),
            "raw_qa_insufficient": evidence["raw_qa_insufficient"].fillna(False),
            "raw_unburned_special": evidence["raw_unburned_special"].fillna(False),
            "raw_unknown": evidence["raw_unknown"].fillna(False),
            "window_partial": evidence["window_coverage_status"].eq("partial"),
            "window_unknown": evidence["window_coverage_status"].eq("unknown"),
            "required_evidence_incomplete": evidence["required_evidence_incomplete"],
        }
    )
    reasons = _reason_rows(reason_frame)
    primary_reason = (
        reasons[reasons["is_primary_reason"]][["event_id", "reason_code"]].rename(
            columns={"reason_code": "reason_primary"}
        )
        if not reasons.empty
        else pd.DataFrame(columns=["event_id", "reason_primary"])
    )
    evidence = evidence.merge(primary_reason, on="event_id", how="left")
    positive = evidence["label"].eq(1).fillna(False).astype(bool)
    evidence["label_reason"] = np.select(
        [
            evidence["label_status"].eq("incomplete").astype(bool),
            positive & evidence["primary_tier"].eq("strong").astype(bool),
            positive,
            evidence["candidate_reason"].eq("scar_outside_window").astype(bool),
            evidence["candidate_reason"].eq("no_scar_match").astype(bool),
        ],
        [
            evidence["reason_primary"].fillna("required_evidence_incomplete"),
            "primary_strong",
            "primary_medium",
            "candidate_scar_outside_window",
            "candidate_no_scar_match",
        ],
        default="primary_weak",
    )
    secondary = (
        reasons[~reasons["is_primary_reason"]]
        .groupby("event_id")["reason_code"]
        .agg(lambda values: ",".join(sorted(values)))
    )
    evidence["label_reason_secondary"] = evidence["event_id"].map(secondary).fillna("")
    evidence["label_rule_version"] = LABEL_RULE_VERSION
    evidence["source_granule_count"] = (
        evidence["event_id"]
        .map(required_obs.groupby("event_id")["source_granule_identity"].nunique())
        .fillna(0)
        .astype("int32")
    )

    # Cell-day aggregation.
    def aggregate_cell(group: pd.DataFrame) -> pd.Series:
        n_incomplete = int((group["label_status"] == "incomplete").sum())
        n_positive = int((group["label"] == 1).sum())
        n_negative = int((group["label"] == 0).sum())
        if n_incomplete:
            label = pd.NA
            status = "incomplete"
            reasons = group.loc[group["label_status"] == "incomplete", "label_reason"]
            reason = reasons.map(REASON_RANK).idxmin() if len(reasons) else None
            reason = reasons.loc[reason] if reason is not None else "required_evidence_incomplete"
        elif n_positive:
            label, status = 1, "positive"
            reason = (
                "primary_strong" if (group["primary_tier"] == "strong").any() else "primary_medium"
            )
        else:
            label, status = 0, "negative"
            if (group["primary_tier"] == "weak").any():
                reason = "primary_weak"
            elif (group["candidate_reason"] == "scar_outside_window").any():
                reason = "candidate_scar_outside_window"
            else:
                reason = "candidate_no_scar_match"
        tier_rank = {"strong": 4, "medium": 3, "weak": 2, "candidate": 1}
        tiers = group["primary_tier"].dropna().tolist()
        audit_tier = max(tiers, key=lambda value: tier_rank.get(value, 0)) if tiers else "candidate"
        return pd.Series(
            {
                "n_events": len(group),
                "n_positive": n_positive,
                "n_negative": n_negative,
                "n_incomplete": n_incomplete,
                "n_strong": int((group["primary_tier"] == "strong").sum()),
                "n_medium": int((group["primary_tier"] == "medium").sum()),
                "n_weak": int((group["primary_tier"] == "weak").sum()),
                "n_candidate": int((group["primary_tier"] == "candidate").sum()),
                "n_no_scar_match": int((group["candidate_reason"] == "no_scar_match").sum()),
                "n_scar_outside_window": int(
                    (group["candidate_reason"] == "scar_outside_window").sum()
                ),
                "n_valid_evidence": int((group["evidence_status"] == "valid").sum()),
                "label": label,
                "label_status": status,
                "label_complete": status != "incomplete",
                "label_reason": reason,
                "audit_tier_max": audit_tier,
                "label_rule_version": LABEL_RULE_VERSION,
            }
        )

    cell = (
        evidence.groupby(["cell_id", "date"], as_index=False)
        .apply(aggregate_cell, include_groups=False)
        .reset_index(drop=True)
    )
    cell["label"] = pd.array(cell["label"], dtype="Int8")
    cell["fingerprint"] = _fingerprint(cell)

    outputs = {
        "hotspot_event_required_period": required,
        "hotspot_event_scar_candidate": candidates,
        "hotspot_event_evidence": evidence,
        "hotspot_event_evidence_reason": reasons,
        "hotspot_event_evidence_source": required_obs[
            [
                "event_id",
                "period",
                "source_status",
                "observation_available",
                "raw_pixel_status",
                "source_granule_identity",
                "source_content_hash",
                "source_file",
                "source_run_id",
            ]
        ].drop_duplicates(),
        "hotspot_cell_day_labeled": cell,
    }
    for name, frame in outputs.items():
        folder = normalized_root / "mcd64a1" / f"dataset={name}"
        folder.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(folder / "part-00000.parquet", index=False)
    return {
        "events": len(evidence),
        "event_positive": int((evidence["label"] == 1).sum()),
        "event_negative": int((evidence["label"] == 0).sum()),
        "event_incomplete": int((evidence["label_status"] == "incomplete").sum()),
        "cell_rows": len(cell),
        "cell_positive": int((cell["label"] == 1).sum()),
        "cell_negative": int((cell["label"] == 0).sum()),
        "cell_incomplete": int((cell["label_status"] == "incomplete").sum()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Build Batch 2B event evidence")
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
        publish_root=args.publish_root,
        batch_root=args.normalized_root / "mcd64a1",
        normalized_root=args.normalized_root,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EventEvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
