from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import heartbeat
import state


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "state" / "seen.json"

    state.save_set(path, {"a", "b"})

    values, error = state.load_set(path)
    assert error is None
    assert values == {"a", "b"}
    assert not (tmp_path / "state" / "seen.json.tmp").exists()


def test_save_is_atomic_on_write_error(monkeypatch, tmp_path) -> None:
    path = tmp_path / "seen.json"
    state.save_set(path, {"lama"})

    def boom(src, dst):
        raise OSError("disk penuh")

    monkeypatch.setattr(os, "replace", boom)

    try:
        state.save_set(path, {"baru"})
    except OSError:
        pass

    # File lama tetap utuh; tidak ada file setengah jadi yang dipakai.
    values, error = state.load_set(path)
    assert error is None
    assert values == {"lama"}


def test_load_reports_corrupt_file(tmp_path) -> None:
    path = tmp_path / "seen.json"
    path.write_text('[{"setengah', encoding="utf-8")

    values, error = state.load_set(path)

    assert values == set()
    assert error is not None and "JSONDecodeError" in error


def test_load_rejects_non_list_payload(tmp_path) -> None:
    path = tmp_path / "seen.json"
    path.write_text('{"bukan": "list"}', encoding="utf-8")

    values, error = state.load_set(path)

    assert values == set()
    assert error is not None and "seharusnya list" in error


def test_backup_moves_corrupt_file(tmp_path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("rusak", encoding="utf-8")

    moved = state.backup(path)

    assert moved is not None
    assert not path.exists()
    assert moved.read_text(encoding="utf-8") == "rusak"


def test_prune_by_date_drops_old_keys() -> None:
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    values = {
        "-0.5|101.5|2026-11-14|0310|N20",
        "-0.5|101.5|2026-11-13|0310|N20",
        "-0.5|101.5|2026-10-01|0310|N20",
        "format-aneh",
    }

    kept = state.prune_by_date(values, days=7, now=now)

    assert "-0.5|101.5|2026-11-14|0310|N20" in kept
    assert "-0.5|101.5|2026-11-13|0310|N20" in kept
    assert "-0.5|101.5|2026-10-01|0310|N20" not in kept
    assert "format-aneh" not in kept


def test_prune_spool_files_removes_only_old_sent_files(tmp_path) -> None:
    old = tmp_path / "source=X" / "batch_old.jsonl.sent"
    new = tmp_path / "source=X" / "batch_new.jsonl.sent"
    pending = tmp_path / "source=X" / "batch_pending.jsonl"
    for path in (old, new, pending):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    old_time = time.time() - 10 * 86400
    os.utime(old, (old_time, old_time))

    removed = state.prune_spool_files(tmp_path, days=7)

    assert removed == 1
    assert not old.exists()
    assert new.exists()
    assert pending.exists()


def test_heartbeat_roundtrip(tmp_path) -> None:
    path = tmp_path / "hb.json"

    heartbeat.beat(path, written=3)

    data = heartbeat.read(path)
    assert data is not None
    assert data["written"] == 3
    assert "ping_at" in data
    assert json.loads(path.read_text(encoding="utf-8"))["written"] == 3


def test_heartbeat_read_missing_returns_none(tmp_path) -> None:
    assert heartbeat.read(tmp_path / "tidak-ada.json") is None
