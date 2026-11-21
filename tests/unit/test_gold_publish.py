from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from batch.gold.publish import (
    ParityError,
    backup_iceberg,
    check_all,
    expire_snapshots,
    load_catalog,
    publish_all,
    publish_table,
    restore_iceberg,
    schema_evolution_demo,
    verify_all,
)


def _write_parquet(
    connection: duckdb.DuckDBPyConnection,
    folder: Path,
    query: str,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"copy ({query}) to '{(folder / 'part.parquet').as_posix()}' "
        "(format parquet)"
    )


@pytest.fixture()
def gold_root(tmp_path: Path) -> Path:
    root = tmp_path / "gold"
    connection = duckdb.connect()
    try:
        for day, count in (("2026-09-01", 10), ("2026-09-02", 4)):
            _write_parquet(
                connection,
                root / "province_daily" / f"date={day}",
                f"select 'Aceh' as province, 'Sumatera' as island, "
                f"{count} as hotspot_count, 5 as scar_pixels_cum, "
                f"cast(1.5 as decimal(18,3)) as frp_sum",
            )
        _write_parquet(
            connection,
            root / "cell_daily" / "date=2026-09-01",
            "select '0044_0033' as cell_id, 'Aceh' as province, "
            "6 as hotspot_count, 1 as label_risk",
        )
        _write_parquet(
            connection,
            root / "burn_scar_monthly" / "burn_month=2026-09",
            "select 'Aceh' as province, 'Sumatera' as island, 7 as scar_pixels",
        )
    finally:
        connection.close()
    return root


@pytest.fixture()
def iceberg_root(tmp_path: Path) -> Path:
    return tmp_path / "iceberg"


def test_publish_all_creates_three_tables(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        summaries = publish_all(catalog, connection, gold_root)
    finally:
        connection.close()

    rows = {summary["table"]: summary["rows"] for summary in summaries}
    assert rows == {
        "gold.cell_daily": 1,
        "gold.province_daily": 2,
        "gold.burn_scar_monthly": 1,
    }
    assert all(summary["snapshot_count"] >= 1 for summary in summaries)


def test_second_full_publish_adds_snapshots(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(catalog, connection, gold_root, mode="full", tables=("province_daily",))
        first = publish_table(
            catalog, connection, gold_root, "province_daily", mode="full"
        )
        second = publish_table(
            catalog, connection, gold_root, "province_daily", mode="full"
        )
    finally:
        connection.close()

    assert first["snapshot_count"] >= 1
    assert second["snapshot_count"] > first["snapshot_count"]
    assert second["rows"] == 2


def test_upsert_replaces_one_partition(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_table(
            catalog, connection, gold_root, "province_daily", mode="full"
        )
        _write_parquet(
            connection,
            gold_root / "province_daily" / "date=2026-09-01",
            "select 'Aceh' as province, 'Sumatera' as island, "
            "99 as hotspot_count, 5 as scar_pixels_cum, cast(1.5 as decimal(18,3)) as frp_sum",
        )
        summary = publish_table(
            catalog,
            connection,
            gold_root,
            "province_daily",
            mode="upsert",
            partition_value=date(2026, 9, 1),
        )
    finally:
        connection.close()

    table = catalog.load_table("gold.province_daily")
    rows = table.scan().to_arrow().to_pydict()
    values = dict(zip(rows["date"], rows["hotspot_count"], strict=True))
    assert values[date(2026, 9, 1)] == 99
    assert values[date(2026, 9, 2)] == 4
    assert summary["rows"] == 2


def test_schema_evolution_adds_new_column(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_table(
            catalog, connection, gold_root, "province_daily", mode="full"
        )
        _write_parquet(
            connection,
            gold_root / "province_daily" / "date=2026-09-01",
            "select 'Aceh' as province, 'Sumatera' as island, "
            "10 as hotspot_count, 5 as scar_pixels_cum, cast(1.5 as decimal(18,3)) as frp_sum, "
            "'catatan' as extra_note",
        )
        _write_parquet(
            connection,
            gold_root / "province_daily" / "date=2026-09-02",
            "select 'Aceh' as province, 'Sumatera' as island, "
            "4 as hotspot_count, 7 as scar_pixels_cum, cast(1.5 as decimal(18,3)) as frp_sum, "
            "'catatan' as extra_note",
        )
        summary = publish_table(
            catalog, connection, gold_root, "province_daily", mode="full"
        )
    finally:
        connection.close()

    assert "extra_note" in summary["columns"]
    table = catalog.load_table("gold.province_daily")
    assert "extra_note" in [field.name for field in table.schema().fields]


def test_schema_evolution_demo(gold_root: Path, iceberg_root: Path) -> None:
    catalog = load_catalog(iceberg_root)

    result = schema_evolution_demo(catalog)

    assert result["columns_before"] == ["id", "label"]
    assert result["columns_after"] == ["id", "label", "note"]
    assert result["snapshot_count"] == 2


def test_backup_and_restore_catalog(
    gold_root: Path,
    iceberg_root: Path,
    tmp_path: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(catalog, connection, gold_root)
    finally:
        connection.close()
    catalog.engine.dispose()

    backup = tmp_path / "backup"
    assert backup_iceberg(iceberg_root, backup)["catalog"] is True
    shutil.rmtree(iceberg_root)
    assert not iceberg_root.exists()

    restored = restore_iceberg(iceberg_root, backup)
    assert restored["catalog"] is True
    restored_catalog = load_catalog(iceberg_root)
    summaries = verify_all(restored_catalog, tables=("province_daily",))
    assert summaries[0]["rows"] == 2
    assert summaries[0]["exists"] is True


def test_strict_publish_writes_state_and_current(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(
            catalog,
            connection,
            gold_root,
            strict=True,
            iceberg_root=iceberg_root,
            run_id="test-run",
        )
    finally:
        connection.close()

    state = json.loads(
        (iceberg_root / "publish_state.json").read_text(encoding="utf-8")
    )
    current = json.loads(
        (iceberg_root / "current.json").read_text(encoding="utf-8")
    )
    assert state["run_id"] == "test-run"
    assert set(state["tables"]) == {
        "cell_daily",
        "province_daily",
        "burn_scar_monthly",
    }
    for name, info in state["tables"].items():
        assert info["parquet"] == info["iceberg"]
        assert info["snapshot_id"] == current["snapshots"][name]


def test_check_passes_after_publish(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(catalog, connection, gold_root)
        checks = check_all(catalog, connection, gold_root)
    finally:
        connection.close()

    assert all(check["ok"] for check in checks)


def test_check_detects_mismatch(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(catalog, connection, gold_root)
        _write_parquet(
            connection,
            gold_root / "province_daily" / "date=2026-09-01",
            "select 'Aceh' as province, 'Sumatera' as island, "
            "999 as hotspot_count, 5 as scar_pixels_cum, "
            "cast(1.5 as decimal(18,3)) as frp_sum",
        )
        checks = check_all(
            catalog,
            connection,
            gold_root,
            tables=("province_daily",),
        )
    finally:
        connection.close()

    assert checks[0]["ok"] is False
    assert (
        checks[0]["parquet"]["hotspot_sum"]
        != checks[0]["iceberg"]["hotspot_sum"]
    )


def test_strict_does_not_write_pointer_on_mismatch(
    gold_root: Path,
    iceberg_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        monkeypatch.setattr(
            "batch.gold.publish.check_all",
            lambda *args, **kwargs: [
                {
                    "table": "gold.cell_daily",
                    "ok": False,
                    "parquet": {"row_count": 1},
                    "iceberg": {"row_count": 0},
                }
            ],
        )
        with pytest.raises(ParityError):
            publish_all(
                catalog,
                connection,
                gold_root,
                strict=True,
                iceberg_root=iceberg_root,
            )
    finally:
        connection.close()

    assert not (iceberg_root / "publish_state.json").exists()
    assert not (iceberg_root / "current.json").exists()


def test_expire_keeps_min_snapshots(
    gold_root: Path,
    iceberg_root: Path,
) -> None:
    catalog = load_catalog(iceberg_root)
    connection = duckdb.connect()
    try:
        publish_all(
            catalog,
            connection,
            gold_root,
            tables=("province_daily",),
        )
        publish_all(
            catalog,
            connection,
            gold_root,
            tables=("province_daily",),
        )
        before = len(
            catalog.load_table("gold.province_daily").metadata.snapshots
        )
        result = expire_snapshots(
            catalog,
            tables=("province_daily",),
            retention_days=0,
            min_snapshots=1,
        )
    finally:
        connection.close()

    table = catalog.load_table("gold.province_daily")
    assert result[0]["before"] == before
    assert result[0]["after"] <= before
    assert result[0]["after"] >= 1
    assert table.current_snapshot() is not None
