"""Quality reports and quarantine output for the Silver layer."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from batch.silver.parquet import ObjectStore, table_from_rows, upload_parquet

DQ_CONTENT_TYPE = "application/json"
QUARANTINE_METADATA = {"kind": "silver-quarantine"}
QUARANTINE_SCHEMA = pa.schema(
    [
        ("source", pa.string()),
        ("dataset", pa.string()),
        ("run_id", pa.string()),
        ("reason", pa.string()),
        ("payload", pa.string()),
        ("quarantined_at", pa.string()),
    ]
)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DQCheck:
    name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DQReport:
    source: str
    dataset: str
    run_id: str
    input_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    checks: list[DQCheck] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def status(self) -> str:
        return "passed" if self.checks and all(check.passed for check in self.checks) else "failed"

    def add_check(self, name: str, passed: bool, **details: Any) -> DQCheck:
        check = DQCheck(name=name, passed=passed, details=details)
        self.checks.append(check)
        return check

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dataset": self.dataset,
            "run_id": self.run_id,
            "status": self.status,
            "generated_at": self.generated_at,
            "counts": {
                "input_rows": self.input_rows,
                "accepted_rows": self.accepted_rows,
                "rejected_rows": self.rejected_rows,
                "duplicate_rows": self.duplicate_rows,
            },
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "details": check.details,
                }
                for check in self.checks
            ],
        }

    def write(self, store: ObjectStore, key: str, *, overwrite: bool = False) -> str:
        body = json.dumps(self.as_dict(), indent=2, ensure_ascii=False).encode("utf-8")
        return store.put_bytes(
            key,
            body,
            content_type=DQ_CONTENT_TYPE,
            metadata={
                "kind": "silver-dq-report",
                "source": self.source,
                "dataset": self.dataset,
                "run-id": self.run_id,
            },
            overwrite=overwrite,
        )


def check_row_count(name: str, actual: int, expected: int) -> DQCheck:
    return DQCheck(
        name=name,
        passed=actual == expected,
        details={
            "actual": actual,
            "expected": expected,
            "difference": actual - expected,
        },
    )


def check_unique(name: str, values: Iterable[Hashable]) -> DQCheck:
    counts = Counter(values)
    duplicate_rows = sum(count - 1 for count in counts.values() if count > 1)
    duplicate_keys = sum(1 for count in counts.values() if count > 1)
    return DQCheck(
        name=name,
        passed=duplicate_rows == 0,
        details={
            "rows": sum(counts.values()),
            "distinct_keys": len(counts),
            "duplicate_rows": duplicate_rows,
            "duplicate_keys": duplicate_keys,
        },
    )


def check_not_null(
    name: str,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> DQCheck:
    row_list = list(rows)
    null_counts = {
        column: sum(1 for row in row_list if row.get(column) is None) for column in columns
    }
    return DQCheck(
        name=name,
        passed=not any(null_counts.values()),
        details={"rows": len(row_list), "null_counts": null_counts},
    )


def quarantine_table(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    dataset: str,
    reason: str,
    run_id: str,
) -> pa.Table:
    payloads = [
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) for row in rows
    ]
    return table_from_rows(
        [
            {
                "source": source,
                "dataset": dataset,
                "run_id": run_id,
                "reason": reason,
                "payload": payload,
                "quarantined_at": utc_now_iso(),
            }
            for payload in payloads
        ],
        schema=QUARANTINE_SCHEMA,
    )


def write_quarantine(
    store: ObjectStore,
    key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    dataset: str,
    reason: str,
    run_id: str,
    overwrite: bool = False,
) -> str:
    table = quarantine_table(
        rows,
        source=source,
        dataset=dataset,
        reason=reason,
        run_id=run_id,
    )
    return upload_parquet(
        store,
        key,
        table,
        metadata={
            **QUARANTINE_METADATA,
            "source": source,
            "dataset": dataset,
            "run-id": run_id,
        },
        overwrite=overwrite,
    )
