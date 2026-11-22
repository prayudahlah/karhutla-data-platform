from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from batch.silver.mcd64a1_event_evidence import (
    _burned_without_scar_candidate,
    _fingerprint,
    build_all,
    tier_for_gap,
    validate_scar_date,
)

ROOT = Path("data/silver/_normalized/mcd64a1")

pytestmark = pytest.mark.skipif(
    not ROOT.exists(),
    reason="data Silver normalized tidak tersedia; tes ini butuh hasil Batch 2B",
)


def _table(name: str) -> pd.DataFrame:
    return pd.read_parquet(ROOT / f"dataset={name}" / "part-00000.parquet")


def _valid_args(**overrides):
    values = {
        "scar_date": date(2026, 9, 1),
        "period": "2026-09",
        "source_status": "available",
        "observation_available": True,
        "raw_pixel_status": "burned",
        "qa_land": True,
        "qa_valid": True,
        "qa_special_condition": 0,
        "burn_date_code": 244,
        "first_day": 237,
        "last_day": 251,
    }
    values.update(overrides)
    return values


def test_b01_strong_gap_0_to_3() -> None:
    e = _table("hotspot_event_evidence")
    rows = e[e["primary_gap_days"].between(0, 3)]
    assert not rows.empty
    assert (rows["primary_tier"] == "strong").all()
    assert (rows["label"] == 1).all()


def test_b02_strong_gap_3_boundary() -> None:
    assert tier_for_gap(0) == "strong"
    assert tier_for_gap(3) == "strong"


def test_b03_medium_gap_4_to_7() -> None:
    assert tier_for_gap(4) == "medium"
    assert tier_for_gap(7) == "medium"
    e = _table("hotspot_event_evidence")
    rows = e[e["primary_gap_days"].between(4, 7)]
    assert not rows.empty
    assert (rows["label"] == 1).all()


def test_b04_medium_gap_7() -> None:
    assert tier_for_gap(7) == "medium"


def test_b05_weak_gap_8() -> None:
    assert tier_for_gap(8) == "weak"
    e = _table("hotspot_event_evidence")
    rows = e[e["primary_gap_days"].between(8, 14)]
    assert not rows.empty
    assert (rows["label"] == 0).all()


def test_b06_weak_gap_14() -> None:
    assert tier_for_gap(14) == "weak"


def test_b07_outside_gap_15() -> None:
    assert tier_for_gap(15) == "candidate"
    e = _table("hotspot_event_evidence")
    rows = e[(e["primary_gap_days"].gt(14)) & (e["evidence_status"] == "valid")]
    assert not rows.empty
    assert (rows["label"] == 0).all()
    assert (rows["primary_tier"] == "candidate").all()


def test_b08_invalid_qa() -> None:
    result = validate_scar_date(**_valid_args(qa_valid=False, raw_pixel_status="qa_insufficient"))
    assert result.status == "invalid"
    assert result.reason == "qa_invalid"


def test_b09_water_or_not_land() -> None:
    result = validate_scar_date(**_valid_args(qa_land=False, raw_pixel_status="water"))
    assert result.status == "invalid"
    assert result.reason == "not_land"


def test_b10_burn_date_mismatch() -> None:
    result = validate_scar_date(**_valid_args(burn_date_code=245))
    assert result.status == "invalid"
    assert result.reason == "burn_date_mismatch"


def test_b11_first_last_not_cover_scar_date() -> None:
    result = validate_scar_date(**_valid_args(first_day=245, last_day=251))
    assert result.status == "invalid"
    assert result.reason == "first_last_not_cover"


def test_b12_missing_granule() -> None:
    result = validate_scar_date(**_valid_args(source_status="missing"))
    assert result.status == "insufficient"
    assert result.reason == "source_missing"


def test_b13_observation_unusable() -> None:
    result = validate_scar_date(**_valid_args(raw_pixel_status="missing"))
    assert result.status == "insufficient"
    assert result.reason == "observation_unusable"


def test_b14_coverage_interval_null() -> None:
    result = validate_scar_date(**_valid_args(first_day=None, last_day=None))
    assert result.status == "insufficient"
    assert result.reason == "first_last_not_cover"


def test_b15_positive_never_wins_over_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["label"] == 1) & (e["evidence_status"] != "valid")]
    assert bad.empty


def test_b16_no_scar_match_is_negative() -> None:
    e = _table("hotspot_event_evidence")
    rows = e[e["candidate_reason"] == "no_scar_match"]
    assert not rows.empty
    assert (rows["label"] == 0).all()
    assert (rows["evidence_status"] == "valid").all()


def test_b17_no_scar_requires_full_coverage() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["candidate_reason"] == "no_scar_match") & (e["window_coverage_status"] != "full")]
    assert bad.empty


def test_b18_outside_window_is_negative() -> None:
    e = _table("hotspot_event_evidence")
    rows = e[e["candidate_reason"] == "scar_outside_window"]
    assert not rows.empty
    assert (rows["label"] == 0).all()


def test_b19_outside_scar_requires_valid_coverage() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["candidate_reason"] == "scar_outside_window") & (e["evidence_status"] != "valid")]
    assert bad.empty


def test_b20_primary_is_nearest_valid_candidate() -> None:
    c = _table("hotspot_event_scar_candidate")
    valid = c[c["validation_status"] == "valid"]
    grouped = valid.groupby("event_id")
    for _event_id, group in grouped:
        primary = group[group["is_primary"]]
        assert len(primary) == 1
        assert primary["gap_days"].iloc[0] == group["gap_days"].min()


def test_b21_tie_break_is_deterministic() -> None:
    c = _table("hotspot_event_scar_candidate")
    ties = c[c["tie_count"] > 1]
    assert not ties.empty
    for _event_id, group in ties.groupby("event_id"):
        primary = group[group["is_primary"]]
        assert len(primary) == 1
        assert primary["match_rank"].iloc[0] == 1
        assert group["tie_count"].iloc[0] == (group["gap_days"] == group["gap_days"].min()).sum()


def test_b22_secondary_candidate_metadata_preserved() -> None:
    c = _table("hotspot_event_scar_candidate")
    multi = c.groupby("event_id").filter(lambda group: len(group) > 1)
    assert not multi.empty
    assert multi["is_primary"].sum() < len(multi)
    assert multi["validation_status"].notna().all()


def test_b23_primary_10_beats_20() -> None:
    assert tier_for_gap(10) == "weak"
    e = _table("hotspot_event_evidence")
    weak = e[(e["primary_gap_days"] == 10) & (e["primary_tier"] == "weak")]
    assert not weak.empty
    assert (weak["candidate_reason"].isna()).all()


def test_b24_cell_day_any_confirmed() -> None:
    c = _table("hotspot_cell_day_labeled")
    rows = c[(c["n_positive"] > 0) & (c["n_incomplete"] == 0)]
    assert not rows.empty
    assert (rows["label"] == 1).all()
    assert (rows["label_status"] == "positive").all()


def test_b25_cell_day_incomplete_priority() -> None:
    c = _table("hotspot_cell_day_labeled")
    rows = c[c["n_incomplete"] > 0]
    assert not rows.empty
    assert rows["label"].isna().all()
    assert (rows["label_status"] == "incomplete").all()


def test_b26_cell_day_all_negative() -> None:
    c = _table("hotspot_cell_day_labeled")
    rows = c[(c["n_incomplete"] == 0) & (c["n_positive"] == 0)]
    assert not rows.empty
    assert (rows["label"] == 0).all()


def test_b27_cell_day_event_count_matches_gold() -> None:
    c = _table("hotspot_cell_day_labeled")
    g = pd.read_parquet("data/gold/published/hotspot_cell_day")
    g["date"] = pd.to_datetime(g["date"].astype(str))
    c["date"] = pd.to_datetime(c["date"])
    joined = g.merge(c, on=["cell_id", "date"], suffixes=("_gold", "_label"))
    assert len(joined) == len(g)
    assert (joined["n_events"] == joined["n_hotspot"]).all()


def test_b28_conflict_is_insufficient() -> None:
    result = validate_scar_date(**_valid_args(source_status="conflict"))
    assert result.status == "insufficient"
    assert result.reason == "source_conflict"


def test_b29_gold_labeled_row_count_and_grain() -> None:
    c = _table("hotspot_cell_day_labeled")
    g = pd.read_parquet("data/gold/published/hotspot_cell_day")
    assert len(c) == len(g)
    assert not c.duplicated(["cell_id", "date"]).any()


def test_b30_source_provenance_observed_rows() -> None:
    source = _table("hotspot_event_evidence_source")
    observed = source[source["observation_available"].astype(bool)]
    assert not observed.empty
    assert observed["source_granule_identity"].notna().all()
    assert observed["source_file"].notna().all()


def test_b31_fingerprint_is_deterministic() -> None:
    c = _table("hotspot_cell_day_labeled").head(20)
    first = _fingerprint(c)
    second = _fingerprint(c)
    assert first.tolist() == second.tolist()
    assert c["fingerprint"].nunique() == len(c)


def test_b32_october_events_are_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    october = e[
        e["date"].astype(str).str.startswith("2026-09-24")
        | e["date"].astype(str).str.startswith("2026-09-25")
        | e["date"].astype(str).str.startswith("2026-09-26")
        | e["date"].astype(str).str.startswith("2026-09-27")
        | e["date"].astype(str).str.startswith("2026-09-28")
        | e["date"].astype(str).str.startswith("2026-09-29")
        | e["date"].astype(str).str.startswith("2026-09-30")
    ]
    assert not october.empty
    assert october["label"].isna().all()
    assert (october["label_status"] == "incomplete").all()


def test_b33_conflict_period_is_incomplete() -> None:
    result = validate_scar_date(**_valid_args(source_status="conflict"))
    assert result.status == "insufficient"


def test_b34_positive_strong_with_missing_granule_is_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["label"] == 1) & (e["missing_observation_count"] > 0)]
    assert bad.empty


def test_b35_positive_medium_with_raw_unusable_is_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["label"] == 1) & (e["raw_unusable_count"] > 0)]
    assert bad.empty


def test_b36_positive_with_partial_coverage_is_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["label"] == 1) & (e["window_coverage_status"] != "full")]
    assert bad.empty


def test_b37_positive_with_candidate_insufficient_is_incomplete() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["label"] == 1) & (e["n_insufficient_candidates"] > 0)]
    assert bad.empty


def test_b38_required_period_excludes_irrelevant_periods() -> None:
    e = _table("hotspot_event_evidence").head(100)
    req = _table("hotspot_event_required_period")
    sample = req[req["event_id"].isin(e["event_id"])]
    assert not sample.empty
    assert sample["required_reason"].isin(["window", "scar_candidate", "window+scar"]).all()


def test_b39_required_period_includes_window() -> None:
    e = _table("hotspot_event_evidence").head(100)
    req = _table("hotspot_event_required_period")
    sample = req[req["event_id"].isin(e["event_id"])]
    window_req = sample[sample["required_reason"].isin(["window", "window+scar"])]
    assert window_req["period"].notna().all()
    assert not window_req.empty


def _required_obs_for_guard() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tile": ["h31v09"],
            "pixel_row": [2026],
            "pixel_col": [2273],
            "period": ["2026-09"],
            "source_status": ["available"],
            "observation_available": [True],
            "raw_status_usable": [True],
            "raw_pixel_status": ["burned"],
            "burn_date_code": [264],
        }
    )


def test_b40_burned_required_observation_without_scar_is_incomplete(tmp_path: Path) -> None:
    publish_root = tmp_path / "published"
    normalized_root = tmp_path / "normalized"
    batch_root = normalized_root / "mcd64a1"
    (publish_root / "firms").mkdir(parents=True)
    (publish_root / "mcd64a1" / "burn_scar").mkdir(parents=True)
    (batch_root / "dataset=pixel_observation").mkdir(parents=True)
    (batch_root / "dataset=granule_status").mkdir(parents=True)

    pd.DataFrame(
        {
            "event_id": ["event-b40"],
            "date": [pd.Timestamp("2026-09-23")],
            "tile": ["h31v09"],
            "pixel_row": [2026],
            "pixel_col": [2273],
            "latitude": [-8.44375],
            "longitude": [141.0013],
        }
    ).to_parquet(publish_root / "firms" / "hotspot_label", index=False)
    pd.DataFrame(
        columns=["tile", "pixel_row", "pixel_col", "burn_date"]
    ).to_parquet(publish_root / "mcd64a1" / "burn_scar" / "part-00000.parquet", index=False)
    pd.DataFrame(
        {
            "tile": ["h31v09"],
            "pixel_row": [2026],
            "pixel_col": [2273],
            "period": ["2026-09"],
            "observation_available": [True],
            "raw_pixel_status": ["burned"],
            "raw_status_usable": [True],
            "qa_land": [True],
            "qa_valid": [True],
            "qa_special_condition": [0],
            "burn_date_code": [264],
            "first_day": [227],
            "last_day": [288],
            "coverage_start_date": [pd.Timestamp("2026-09-01")],
            "coverage_end_date": [pd.Timestamp("2026-09-30")],
            "source_granule_identity": ["h31v09|2026-09"],
            "source_content_hash": ["abc"],
            "source_file": ["bronze/h31v09.hdf"],
            "source_run_id": ["run"],
        }
    ).to_parquet(batch_root / "dataset=pixel_observation" / "part-00000.parquet", index=False)
    pd.DataFrame(
        {"tile": ["h31v09"], "period": ["2026-09"], "source_status": ["available"]}
    ).to_parquet(batch_root / "dataset=granule_status" / "part-00000.parquet", index=False)

    build_all(
        publish_root=publish_root,
        batch_root=batch_root,
        normalized_root=normalized_root,
    )

    evidence = pd.read_parquet(
        normalized_root / "mcd64a1" / "dataset=hotspot_event_evidence" / "part-00000.parquet"
    )
    assert evidence.iloc[0]["label_status"] == "incomplete"
    assert pd.isna(evidence.iloc[0]["label"])
    assert evidence.iloc[0]["reason_primary"] == "required_evidence_incomplete"
    assert bool(evidence.iloc[0]["burned_without_scar_candidate"]) is True
    assert pd.isna(evidence.iloc[0]["candidate_reason"])

    cell = pd.read_parquet(
        normalized_root / "mcd64a1" / "dataset=hotspot_cell_day_labeled" / "part-00000.parquet"
    )
    assert cell.iloc[0]["label_status"] == "incomplete"


def test_b42_existing_candidate_is_not_flagged() -> None:
    required_obs = _required_obs_for_guard()
    scars = pd.DataFrame(
        {
            "tile": ["h31v09"],
            "pixel_row": [2026],
            "pixel_col": [2273],
            "burn_date": [date(2026, 9, 21)],
        }
    )

    guard = _burned_without_scar_candidate(required_obs, scars)

    assert bool(guard.iloc[0]) is False


def test_b43_no_scar_event_with_burned_observation_is_not_negative() -> None:
    e = _table("hotspot_event_evidence")
    bad = e[(e["candidate_reason"] == "no_scar_match") & e["burned_without_scar_candidate"]]

    assert bad.empty


def test_b44_boundary_bbox_event_and_cell_are_consistent() -> None:
    e = _table("hotspot_event_evidence")
    event = e[e["event_id"] == "0400c037e3f480058e34d7b5f77e409980c4ece2"]
    assert len(event) == 1
    assert event.iloc[0]["label"] == 1
    assert event.iloc[0]["primary_tier"] == "strong"
    assert event.iloc[0]["primary_gap_days"] == 2

    cell = _table("hotspot_cell_day_labeled")
    row = cell[(cell["cell_id"] == "0010_0183") & (cell["date"].astype(str) == "2026-09-23")]
    assert len(row) == 1
    assert row.iloc[0]["label"] == 1
    assert row.iloc[0]["n_positive"] == 4
    assert row.iloc[0]["n_negative"] == 9
