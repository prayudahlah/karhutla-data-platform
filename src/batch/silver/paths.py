"""Canonical object keys for the Silver layer.

Silver keeps the Bronze source/dataset convention so DuckDB can discover
partitions without dataset-specific path logic:

    silver/_normalized/<source>/dataset=<dataset>/date=YYYY-MM-DD/part-00000.parquet
    silver/<source>/dataset=<dataset>/date=YYYY-MM-DD/part-00000.parquet

Normalized files are format-only output. Final Silver tables are written by
dbt after deduplication and quality rules have been applied.
"""

from __future__ import annotations

import re
from datetime import date, datetime

SILVER_ROOT = "silver"
NORMALIZED_ROOT = "silver/_normalized"
QUARANTINE_ROOT = "silver/_quarantine"
DQ_ROOT = "silver/_dq"
MANIFEST_ROOT = "silver/manifests"

_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SilverPathError(ValueError):
    """Raised when a Silver path component is unsafe or malformed."""


def _segment(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise SilverPathError(f"{field} must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not _SEGMENT_RE.fullmatch(cleaned):
        raise SilverPathError(
            f"{field} must match {_SEGMENT_RE.pattern!r} (lowercase snake_case), got {value!r}"
        )
    return cleaned


def _run_id(value: str) -> str:
    if not isinstance(value, str):
        raise SilverPathError(f"run_id must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not _RUN_ID_RE.fullmatch(cleaned):
        raise SilverPathError(f"run_id contains unsafe characters: {value!r}")
    return cleaned


def _part(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SilverPathError(f"part must be an integer, got {type(value).__name__}")
    if value < 0:
        raise SilverPathError(f"part must be zero or greater, got {value}")
    return value


def partition_date(value: date | datetime | str) -> str:
    """Return the canonical ``YYYY-MM-DD`` partition value."""
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value.strip())
        except ValueError as exc:
            raise SilverPathError(
                f"date must be YYYY-MM-DD, got {value!r}"
            ) from exc

    if not isinstance(value, date):
        raise SilverPathError(
            f"date must be a date, datetime, or YYYY-MM-DD string, got {type(value).__name__}"
        )
    return value.isoformat()


def _dataset_prefix(root: str, source: str, dataset: str, date_value: date | datetime | str) -> str:
    return (
        f"{root}/{_segment(source, 'source')}"
        f"/dataset={_segment(dataset, 'dataset')}"
        f"/date={partition_date(date_value)}"
    )


def normalized_prefix(
    source: str,
    dataset: str,
    date_value: date | datetime | str,
) -> str:
    """Prefix for format-normalized Parquet before deduplication."""
    return _dataset_prefix(NORMALIZED_ROOT, source, dataset, date_value)


def normalized_key(
    source: str,
    dataset: str,
    date_value: date | datetime | str,
    part: int = 0,
) -> str:
    return f"{normalized_prefix(source, dataset, date_value)}/part-{_part(part):05d}.parquet"


def silver_prefix(
    source: str,
    dataset: str,
    date_value: date | datetime | str,
) -> str:
    """Prefix for the final, deduplicated Silver table."""
    return _dataset_prefix(SILVER_ROOT, source, dataset, date_value)


def silver_key(
    source: str,
    dataset: str,
    date_value: date | datetime | str,
    part: int = 0,
) -> str:
    return f"{silver_prefix(source, dataset, date_value)}/part-{_part(part):05d}.parquet"


def quarantine_key(
    source: str,
    dataset: str,
    date_value: date | datetime | str,
    part: int = 0,
) -> str:
    return (
        f"{_dataset_prefix(QUARANTINE_ROOT, source, dataset, date_value)}"
        f"/part-{_part(part):05d}.parquet"
    )


def dq_report_key(source: str, dataset: str, run_id: str) -> str:
    return (
        f"{DQ_ROOT}/{_segment(source, 'source')}"
        f"/dataset={_segment(dataset, 'dataset')}"
        f"/run_id={_run_id(run_id)}.json"
    )


def manifest_key(run_id: str) -> str:
    return f"{MANIFEST_ROOT}/run_id={_run_id(run_id)}.json"
