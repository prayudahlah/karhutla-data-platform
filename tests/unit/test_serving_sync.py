from __future__ import annotations

import json
from pathlib import Path

import pytest

from serving.sync_marts import _active_snapshots


def test_active_snapshots_reads_current_pointer(tmp_path: Path) -> None:
    (tmp_path / "current.json").write_text(
        json.dumps(
            {
                "snapshots": {
                    "cell_daily": 1,
                    "province_daily": 2,
                    "burn_scar_monthly": 3,
                }
            }
        ),
        encoding="utf-8",
    )

    assert _active_snapshots(tmp_path) == {
        "cell_daily": 1,
        "province_daily": 2,
        "burn_scar_monthly": 3,
    }


def test_active_snapshots_requires_pointer(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _active_snapshots(tmp_path)


def test_active_snapshots_requires_all_tables(tmp_path: Path) -> None:
    (tmp_path / "current.json").write_text(
        json.dumps({"snapshots": {"cell_daily": 1}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        _active_snapshots(tmp_path)
