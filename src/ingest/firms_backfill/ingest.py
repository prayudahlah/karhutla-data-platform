"""Backfill hotspot FIRMS historis ke Bronze.

Satu periode diambil per sumber dalam jendela lima hari, lalu ditulis sebagai
JSONL dengan bentuk yang sama seperti keluaran stream. Nama objek ditentukan
oleh sumber dan rentang tanggal, jadi menjalankan ulang periode yang sama
melewati objek yang sudah ada.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from common.config import FirmsBackfillSettings
from common.run import new_run_id
from common.storage import BronzeStore, ObjectAlreadyExistsError
from ingest.firms_backfill.client import FirmsAreaClient, month_windows
from ingest.firms_backfill.contract import to_event

logger = logging.getLogger(__name__)

CONTENT_TYPE_JSONL = "application/x-ndjson"


@dataclass(frozen=True)
class WindowFailure:
    source: str
    start: str
    error_type: str
    message: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def object_key(
    prefix: str,
    *,
    source: str,
    period: str,
    start: str,
    end: str,
) -> str:
    """Kunci memakai periode data, bukan waktu jalan.

    Dengan begitu menjalankan ulang bulan yang sama menghasilkan kunci yang
    sama, sehingga backfill idempoten tanpa perlu mengingat kapan terakhir
    dijalankan.
    """
    return (
        f"{prefix.strip('/')}/dataset=hotspot/source={source}"
        f"/period={period}/part-backfill-{source}-{start}-{end}.jsonl"
    )


def manifest_key(prefix: str, ingest_date: str, run_id: str) -> str:
    return f"{prefix.strip('/')}/manifests/ingest_date={ingest_date}/run_id={run_id}.json"


def serialize_jsonl(events: Sequence[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for event in events
    )


def backfill_month(
    store: BronzeStore,
    settings: FirmsBackfillSettings,
    *,
    month: str,
    prefix: str,
    run_id: str | None = None,
    overwrite: bool = False,
    client: FirmsAreaClient | None = None,
) -> dict[str, Any]:
    """Tarik satu bulan untuk semua sumber, lalu tulis ke Bronze."""
    run_id = run_id or new_run_id()
    started = utc_now()
    ingest_date = started[:10]
    windows = month_windows(month, settings.window_days)

    own_client = client is None
    area = client or FirmsAreaClient(settings)

    entries: list[dict[str, Any]] = []
    failures: list[WindowFailure] = []
    try:
        for source in settings.sources:
            for start_day, end_day in windows:
                days = (end_day - start_day).days + 1
                key = object_key(
                    prefix,
                    source=source,
                    period=month,
                    start=start_day.isoformat(),
                    end=end_day.isoformat(),
                )
                if not overwrite and store.object_exists(key):
                    entries.append(
                        {
                            "source": source,
                            "start": start_day.isoformat(),
                            "end": end_day.isoformat(),
                            "key": key,
                            "action": "skipped",
                            "events": 0,
                        }
                    )
                    continue

                try:
                    rows = area.fetch_window(source, start_day, days)
                    events = [to_event(row, source=source, ingested_at=started) for row in rows]
                    digest = store.put_bytes(
                        key,
                        serialize_jsonl(events),
                        content_type=CONTENT_TYPE_JSONL,
                        metadata={
                            "run-id": run_id,
                            "source": "firms",
                            "kind": "backfill",
                            "dataset": "hotspot",
                        },
                        overwrite=overwrite,
                    )
                    entries.append(
                        {
                            "source": source,
                            "start": start_day.isoformat(),
                            "end": end_day.isoformat(),
                            "key": key,
                            "action": "written",
                            "events": len(events),
                            "sha256": digest,
                        }
                    )
                    logger.info("%s %s: %d event", source, start_day, len(events))
                except ObjectAlreadyExistsError:
                    entries.append(
                        {
                            "source": source,
                            "start": start_day.isoformat(),
                            "end": end_day.isoformat(),
                            "key": key,
                            "action": "skipped",
                            "events": 0,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - isolasi per jendela
                    failures.append(
                        WindowFailure(
                            source=source,
                            start=start_day.isoformat(),
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    )
                    logger.exception("Gagal backfill %s %s", source, start_day)
    finally:
        if own_client:
            area.close()

    written = sum(entry["events"] for entry in entries)
    manifest = {
        "schema_version": 1,
        "source": "firms-backfill",
        "run_id": run_id,
        "month": month,
        "started_at": started,
        "finished_at": utc_now(),
        "status": "partial" if failures and entries else ("failed" if failures else "success"),
        "summary": {
            "windows": len(windows) * len(settings.sources),
            "windows_written": sum(1 for e in entries if e["action"] == "written"),
            "windows_skipped": sum(1 for e in entries if e["action"] == "skipped"),
            "windows_failed": len(failures),
            "events_written": written,
        },
        "entries": entries,
        "failures": [
            {
                "source": f.source,
                "start": f.start,
                "error_type": f.error_type,
                "message": f.message,
            }
            for f in failures
        ],
    }
    mkey = manifest_key(prefix, ingest_date, run_id)
    store.put_json(mkey, manifest, metadata={"run-id": run_id, "kind": "manifest"})
    return {"manifest_key": mkey, **manifest["summary"], "status": manifest["status"]}
