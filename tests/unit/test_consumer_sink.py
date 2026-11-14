from __future__ import annotations

import pytest
from sink import GarageBronzeSink, LocalBronzeSink, join_lines, part_key

from common.storage import ObjectAlreadyExistsError


def test_part_key_is_relative_and_offset_scoped() -> None:
    key = part_key("MODIS_NRT", "2026-11-14", "05", 1, 7, 9)

    assert key == (
        "source=MODIS_NRT/ingest_date=2026-11-14/ingest_hour=05/"
        "part-p1-000000000007-000000000009.jsonl"
    )


def test_join_lines_adds_missing_newline() -> None:
    assert join_lines([b'{"a":1}', b'{"b":2}\n']) == b'{"a":1}\n{"b":2}\n'


class FakeStore:
    """Cukup untuk menguji GarageBronzeSink tanpa boto3/Garage."""

    bucket = "lakehouse"

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or ())
        self.calls: list[tuple[str, bytes, str, dict[str, str] | None]] = []

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        self.calls.append((key, body, content_type, metadata))
        if key in self.existing:
            raise ObjectAlreadyExistsError(f"exists: {key}")
        self.existing.add(key)
        return "digest"


def test_garage_sink_prefixes_key_and_uses_ndjson() -> None:
    store = FakeStore()
    sink = GarageBronzeSink(store, "bronze/firms")

    location = sink.write("source=X/ingest_date=2026-11-14/a.jsonl", [b'{"a":1}'])

    assert location == "bronze/firms/source=X/ingest_date=2026-11-14/a.jsonl"
    key, body, content_type, metadata = store.calls[0]
    assert key == location
    assert body == b'{"a":1}\n'
    assert content_type == "application/x-ndjson"
    assert metadata == {"kind": "firms-hotspot-batch"}


def test_garage_sink_treats_existing_object_as_success() -> None:
    store = FakeStore(existing={"bronze/firms/a.jsonl"})
    sink = GarageBronzeSink(store, "bronze/firms")

    # Retry setelah upload sukses tapi commit offset gagal: bukan error.
    assert sink.write("a.jsonl", [b"{}"]) == "bronze/firms/a.jsonl"


def test_garage_sink_reraises_other_errors() -> None:
    class BrokenStore(FakeStore):
        def put_bytes(self, *args, **kwargs) -> str:
            raise RuntimeError("garage down")

    with pytest.raises(RuntimeError, match="garage down"):
        GarageBronzeSink(BrokenStore(), "bronze/firms").write("a.jsonl", [b"{}"])


def test_local_sink_is_idempotent(tmp_path) -> None:
    sink = LocalBronzeSink(tmp_path)

    first = sink.write("source=X/a.jsonl", [b'{"a":1}'])
    second = sink.write("source=X/a.jsonl", [b'{"a":2}'])

    assert first == second
    assert first.read_text(encoding="utf-8") == '{"a":1}\n'
