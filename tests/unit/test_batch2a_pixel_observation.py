from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from batch.silver.mcd64a1_coverage import (
    PeriodObservation,
    doy_to_date,
    validate_window_coverage,
)
from batch.silver.mcd64a1_pixel import (
    _decode_raw_status,
    build_status,
    resolve_identity,
)

NORMALIZED_ROOT = Path(os.getenv("SILVER_NORMALIZED_ROOT", "data/silver/_normalized")) / "mcd64a1"


def _table(name: str) -> pd.DataFrame:
    return pd.read_parquet(NORMALIZED_ROOT / f"dataset={name}" / "part-00000.parquet")


def _inventory(
    tile: str,
    period: str,
    identity: str,
    hash_value: str,
    read_status: str = "ok",
    metadata: bool = True,
) -> dict:
    return {
        "tile": tile,
        "period": period,
        "granule_identity": identity,
        "read_status": read_status,
        "metadata_complete": metadata,
        "raster_content_hash": hash_value,
    }


def test_a01_producer_identity_is_used() -> None:
    inventory = _table("granule_inventory")
    assert set(inventory["identity_source"]) == {"producer_id"}
    assert inventory["granule_identity"].notna().all()


def test_a02_fallback_identity_is_deterministic() -> None:
    first, source = resolve_identity(None, source_uri="s3://lakehouse/a.hdf", file_hash="abc")
    second, source2 = resolve_identity(None, source_uri="s3://lakehouse/a.hdf", file_hash="abc")
    assert source == source2 == "fallback"
    assert first == second


def test_a03_missing_identity_is_not_arbitrary() -> None:
    identity, source = resolve_identity(None, source_uri="s3://lakehouse/a.hdf", file_hash=None)
    assert identity is None
    assert source == "missing"


def test_a04_granule_status_available() -> None:
    inventory = pd.DataFrame([_inventory("h01v01", "2026-09", "g1", "hash1")])
    required = pd.DataFrame(
        [{"tile": "h01v01", "pixel_row": 1, "pixel_col": 2, "period": "2026-09"}]
    )
    status = build_status(inventory, required)
    assert status.iloc[0]["source_status"] == "available"
    assert status.iloc[0]["canonical_granule_identity"] == "g1"


def test_a05_granule_status_identical_duplicate() -> None:
    inventory = pd.DataFrame(
        [
            _inventory("h01v01", "2026-09", "g1", "hash1"),
            _inventory("h01v01", "2026-09", "g2", "hash1"),
        ]
    )
    required = pd.DataFrame(
        [{"tile": "h01v01", "pixel_row": 1, "pixel_col": 2, "period": "2026-09"}]
    )
    status = build_status(inventory, required)
    assert status.iloc[0]["source_status"] == "identical_duplicate"
    assert status.iloc[0]["candidate_count"] == 2


def test_a06_granule_status_conflict() -> None:
    inventory = pd.DataFrame(
        [
            _inventory("h01v01", "2026-09", "g1", "hash1"),
            _inventory("h01v01", "2026-09", "g2", "hash2"),
        ]
    )
    required = pd.DataFrame(
        [{"tile": "h01v01", "pixel_row": 1, "pixel_col": 2, "period": "2026-09"}]
    )
    status = build_status(inventory, required)
    assert status.iloc[0]["source_status"] == "conflict"
    assert pd.isna(status.iloc[0]["canonical_granule_identity"])


def test_a07_granule_status_missing() -> None:
    inventory = pd.DataFrame([_inventory("h01v01", "2026-08", "g1", "hash1")])
    required = pd.DataFrame(
        [{"tile": "h01v01", "pixel_row": 1, "pixel_col": 2, "period": "2026-09"}]
    )
    status = build_status(inventory, required)
    row = status.loc[status["period"] == "2026-09"].iloc[0]
    assert row["source_status"] == "missing"


def test_a08_granule_status_metadata_incomplete() -> None:
    inventory = pd.DataFrame([_inventory("h01v01", "2026-09", "g1", "hash1", "error", False)])
    required = pd.DataFrame(
        [{"tile": "h01v01", "pixel_row": 1, "pixel_col": 2, "period": "2026-09"}]
    )
    status = build_status(inventory, required)
    assert status.iloc[0]["source_status"] == "metadata_incomplete"


def test_a09_required_keys_are_unique() -> None:
    required = _table("pixel_period_required")
    assert not required.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any()


def test_a10_observation_keys_are_unique() -> None:
    observation = _table("pixel_observation")
    assert not observation.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any()


def test_a11_no_unexpected_observation() -> None:
    required = _table("pixel_period_required")
    observation = _table("pixel_observation")
    keys = ["tile", "pixel_row", "pixel_col", "period"]
    merged = observation[keys].merge(required[keys], on=keys, how="left", indicator=True)
    assert (merged["_merge"] == "left_only").sum() == 0


def test_a12_reconciliation_sum_matches_required() -> None:
    required = _table("pixel_period_required")
    reconciliation = _table("pixel_period_reconciliation")
    assert len(reconciliation) == len(required)


def test_a13_raw_burned() -> None:
    status = _decode_raw_status(np.array([100]), np.array([3]))
    assert status[0] == "burned"


def test_a14_raw_unburned() -> None:
    status = _decode_raw_status(np.array([0]), np.array([3]))
    assert status[0] == "unburned"


def test_a15_raw_unburned_special() -> None:
    status = _decode_raw_status(np.array([0]), np.array([3 | (1 << 5)]))
    assert status[0] == "unburned_special"


def test_a16_raw_missing_minus_one() -> None:
    status = _decode_raw_status(np.array([-1]), np.array([3]))
    assert status[0] == "missing"


def test_a17_raw_water_minus_two() -> None:
    status = _decode_raw_status(np.array([-2]), np.array([3]))
    assert status[0] == "water"


def test_a18_raw_qa_insufficient() -> None:
    status = _decode_raw_status(np.array([0]), np.array([1]))
    assert status[0] == "qa_insufficient"


def test_a19_qa_bit2_is_preserved() -> None:
    observation = _table("pixel_observation")
    assert observation["qa_shortened_period"].dtype == bool
    assert observation["qa_shortened_period"].any()


def test_a20_qa_bit3_is_preserved() -> None:
    observation = _table("pixel_observation")
    assert observation["qa_contextual_relabel"].dtype == bool
    assert observation["qa_contextual_relabel"].any()


def test_a21_special_6_and_7_are_unknown() -> None:
    status = _decode_raw_status(np.array([0, 0]), np.array([3 | (6 << 5), 3 | (7 << 5)]))
    assert list(status) == ["unknown", "unknown"]


def test_a22_window_coverage_full() -> None:
    observations = {
        "2026-08": PeriodObservation("2026-08", "available", True, 237, 243),
        "2026-09": PeriodObservation("2026-09", "available", True, 244, 251),
    }
    result = validate_window_coverage(date(2026, 9, 1), observations)
    assert result.status == "full"
    assert not result.missing_dates


def test_a23_window_coverage_partial() -> None:
    observations = {
        "2026-08": PeriodObservation("2026-08", "available", True, 239, 243),
        "2026-09": PeriodObservation("2026-09", "available", True, 244, 251),
    }
    result = validate_window_coverage(date(2026, 9, 1), observations)
    assert result.status == "partial"
    assert result.missing_dates


def test_a24_window_coverage_unknown_without_source() -> None:
    observations = {
        "2026-08": PeriodObservation("2026-08", "missing", False, None, None),
        "2026-09": PeriodObservation("2026-09", "missing", False, None, None),
    }
    result = validate_window_coverage(date(2026, 9, 1), observations)
    assert result.status == "unknown"


def test_a25_window_coverage_cross_month() -> None:
    observations = {
        "2026-08": PeriodObservation("2026-08", "available", True, 237, 243),
        "2026-09": PeriodObservation("2026-09", "available", True, 244, 251),
    }
    result = validate_window_coverage(date(2026, 9, 1), observations)
    assert result.window_start == date(2026, 8, 25)
    assert result.window_end == date(2026, 9, 8)
    assert result.status == "full"


def test_a26_window_coverage_cross_year_and_leap() -> None:
    assert doy_to_date(2028, 60) == date(2028, 2, 29)
    assert doy_to_date(2027, 366) is None
    observations = {
        "2025-12": PeriodObservation("2025-12", "available", True, 358, 365),
        "2026-01": PeriodObservation("2026-01", "available", True, 1, 8),
    }
    result = validate_window_coverage(date(2026, 1, 1), observations)
    assert result.status == "full"


def test_a27_required_includes_scar_periods() -> None:
    required = _table("pixel_period_required")
    assert required["required_for_scar"].any()


def test_a28_observation_provenance_is_complete() -> None:
    observation = _table("pixel_observation")
    for column in [
        "source_granule_identity",
        "source_content_hash",
        "source_file",
        "source_run_id",
    ]:
        assert observation[column].notna().all()


def test_a29_october_is_missing_not_observed() -> None:
    observation = _table("pixel_observation")
    reconciliation = _table("pixel_period_reconciliation")
    assert (observation["period"] == "2026-10").sum() == 0
    assert (reconciliation["reconciliation_category"] == "missing_granule").sum() > 0


def test_a30_identity_is_deterministic_across_runs() -> None:
    first = resolve_identity(None, source_uri="s3://lakehouse/a.hdf", file_hash="abc")
    second = resolve_identity(None, source_uri="s3://lakehouse/a.hdf", file_hash="abc")
    assert first == second


def test_a31_reconciliation_categories_are_exclusive() -> None:
    reconciliation = _table("pixel_period_reconciliation")
    categories = {
        "observed_usable",
        "observed_unusable",
        "missing_granule",
        "granule_conflict",
        "metadata_incomplete",
        "source_unknown",
        "extraction_error",
        "other_explained",
    }
    assert set(reconciliation["reconciliation_category"]).issubset(categories)
    assert not reconciliation.duplicated(["tile", "pixel_row", "pixel_col", "period"]).any()
