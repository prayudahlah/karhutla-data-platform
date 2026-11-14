"""Identitas run dan timestamp yang dipakai bersama semua job ingest.

Dipisah dari modul ingest tertentu supaya sumber dan batch tidak saling
mengimpor hanya untuk memakai pembuat run_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    """Run id berbentuk YYYYMMDDTHHMMSSZ-xxxxxxxx."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def run_date_from_run_id(run_id: str) -> str:
    date_part = run_id[:8]
    try:
        parsed = datetime.strptime(date_part, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Invalid run_id {run_id!r}; expected YYYYMMDDTHHMMSSZ-suffix") from exc
    return parsed.strftime("%Y-%m-%d")
