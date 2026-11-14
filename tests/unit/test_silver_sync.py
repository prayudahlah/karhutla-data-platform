from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from batch.silver.sync import SyncError, pull, push

NORMALIZED_KEY = "silver/_normalized/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"
OTHER_KEY = "silver/_normalized/mcd64a1/dataset=burn_scar/date=2026-09-09/part-00000.parquet"


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        if key in self.objects and not overwrite:
            raise FileExistsError(key)
        self.objects[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return "sha"

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]["body"]

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


def _store() -> FakeStore:
    store = FakeStore()
    store.objects[NORMALIZED_KEY] = {"body": b"firms", "content_type": "", "metadata": {}}
    store.objects[OTHER_KEY] = {"body": b"scar", "content_type": "", "metadata": {}}
    return store


def test_pull_writes_mirror_with_same_layout(tmp_path: Path) -> None:
    result = pull(_store(), local_root=tmp_path)

    assert result["downloaded"] == 2
    assert (
        tmp_path / "firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"
    ).read_bytes() == b"firms"
    assert (tmp_path / "mcd64a1/dataset=burn_scar/date=2026-09-09/part-00000.parquet").exists()


def test_pull_is_idempotent(tmp_path: Path) -> None:
    pull(_store(), local_root=tmp_path)

    second = pull(_store(), local_root=tmp_path)

    assert second["downloaded"] == 0
    assert second["skipped"] == 2


def test_pull_filters_by_source_and_month(tmp_path: Path) -> None:
    result = pull(_store(), local_root=tmp_path, source="firms", month="2026-09")

    assert result["keys"] == 1
    assert (tmp_path / "firms/dataset=hotspot/date=2026-09-08/part-00000.parquet").exists()
    assert not (tmp_path / "mcd64a1").exists()


def test_pull_without_objects_raises(tmp_path: Path) -> None:
    with pytest.raises(SyncError):
        pull(FakeStore(), local_root=tmp_path)


def _published(tmp_path: Path, source: str = "firms", dataset: str = "hotspot") -> Path:
    folder = tmp_path / source / dataset / "date=2026-09-08"
    folder.mkdir(parents=True)
    (folder / "part-00000.parquet").write_bytes(b"parquet")
    return tmp_path


def test_push_uploads_with_silver_layout(tmp_path: Path) -> None:
    published = _published(tmp_path)
    store = FakeStore()

    result = push(store, local_root=published)

    assert result["uploaded"] == 1
    assert "silver/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet" in store.objects
    assert (
        store.objects["silver/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"]["body"]
        == b"parquet"
    )


def test_push_overwrites_by_default(tmp_path: Path) -> None:
    published = _published(tmp_path)
    store = FakeStore()
    push(store, local_root=published)
    (published / "firms/hotspot/date=2026-09-08/part-00000.parquet").write_bytes(b"baru")

    push(store, local_root=published)

    assert (
        store.objects["silver/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"]["body"]
        == b"baru"
    )


def test_push_can_refuse_overwrite(tmp_path: Path) -> None:
    published = _published(tmp_path)
    store = FakeStore()
    push(store, local_root=published)

    with pytest.raises(FileExistsError):
        push(store, local_root=published, overwrite=False)


def test_push_filters_by_source(tmp_path: Path) -> None:
    published = _published(tmp_path, source="firms")
    _published(published, source="mcd64a1", dataset="burn_scar")
    store = FakeStore()

    result = push(store, local_root=published, source="firms")

    assert result["uploaded"] == 1
    assert all("mcd64a1" not in key for key in store.objects)


def test_push_rejects_flat_layout(tmp_path: Path) -> None:
    (tmp_path / "date=2026-09-08").mkdir(parents=True)
    (tmp_path / "date=2026-09-08/part.parquet").write_bytes(b"x")

    with pytest.raises(SyncError):
        push(FakeStore(), local_root=tmp_path)


def test_push_without_files_raises(tmp_path: Path) -> None:
    with pytest.raises(SyncError):
        push(FakeStore(), local_root=tmp_path)


def test_mirror_path_strips_silver_prefix() -> None:
    from batch.silver.sync import mirror_path

    path = mirror_path(
        Path("/tmp/x"),
        "silver/_normalized/firms/dataset=hotspot/date=2026-09-08/part.parquet",
    )

    assert path == Path("/tmp/x/firms/dataset=hotspot/date=2026-09-08/part.parquet")


def test_publish_table_writes_remote_and_local(tmp_path: Path) -> None:
    import pyarrow as pa

    from batch.silver.parquet import read_parquet_bytes
    from batch.silver.sync import publish_table

    store = FakeStore()
    table = pa.table({"a": [1, 2]})
    key = "silver/_normalized/firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"

    publish_table(store, key, table, local_root=tmp_path)

    assert key in store.objects
    local = tmp_path / "firms/dataset=hotspot/date=2026-09-08/part-00000.parquet"
    assert read_parquet_bytes(local.read_bytes()).num_rows == 2


def test_publish_table_without_local_root_only_remote() -> None:
    import pyarrow as pa

    from batch.silver.sync import publish_table

    store = FakeStore()
    key = "silver/_normalized/firms/dataset=hotspot/date=2026-09-08/part.parquet"

    publish_table(store, key, pa.table({"a": [1]}))

    assert key in store.objects
