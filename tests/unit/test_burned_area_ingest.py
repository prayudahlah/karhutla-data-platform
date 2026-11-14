from __future__ import annotations

import json
from typing import Any

import pytest

from common.config import BurnedAreaSettings
from common.storage import ObjectAlreadyExistsError, ObjectNotFoundError, sha256_hex
from ingest.burned_area.cmr import Granule
from ingest.burned_area.download import DownloadError
from ingest.burned_area.ingest import (
    ingest_granules,
    manifest_key,
    object_key,
    verify_run,
)

RUN_ID = "20261114T090000Z-abcdef12"


class FakeStore:
    bucket = "lakehouse"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

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
            raise ObjectAlreadyExistsError(key)
        self.objects[key] = body
        return sha256_hex(body)

    def put_json(
        self,
        key: str,
        payload: Any,
        *,
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        body = json.dumps(payload).encode("utf-8")
        return self.put_bytes(key, body, metadata=metadata, overwrite=overwrite)

    def head_object(self, key: str) -> dict[str, Any]:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return {"ContentLength": len(self.objects[key])}

    def read_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]

    def read_json(self, key: str) -> Any:
        return json.loads(self.read_bytes(key).decode("utf-8"))

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


class FakeDownloader:
    def __init__(self, payloads: dict[str, bytes], failing: set[str] | None = None) -> None:
        self.payloads = payloads
        self.failing = failing or set()
        self.calls: list[str] = []

    def fetch(self, granule: Granule) -> bytes:
        self.calls.append(granule.granule_id)
        if granule.granule_id in self.failing:
            raise DownloadError(f"gagal {granule.granule_id}")
        return self.payloads[granule.granule_id]


def _granule(tile: str, granule_id: str | None = None) -> Granule:
    granule_id = granule_id or f"MCD64A1.A2026244.{tile}.061.2026314124402"
    return Granule(
        granule_id=granule_id,
        month="2026-09",
        tile=tile,
        size_bytes=1000,
        url=f"https://example.invalid/{granule_id}.hdf",
    )


def _settings() -> BurnedAreaSettings:
    return BurnedAreaSettings(token="token", bronze_prefix="bronze/mcd64a1")


def test_object_key_uses_granule_identity() -> None:
    key = object_key("bronze/mcd64a1", _granule("h28v09"))

    assert key == (
        "bronze/mcd64a1/month=2026-09/tile=h28v09/MCD64A1.A2026244.h28v09.061.2026314124402.hdf"
    )


def test_object_key_strips_trailing_slash() -> None:
    key = object_key("/bronze/mcd64a1/", _granule("h28v09"))

    assert key.startswith("bronze/mcd64a1/month=2026-09")


def test_manifest_key_uses_run_date() -> None:
    key = manifest_key("bronze/mcd64a1", RUN_ID)

    assert key == f"bronze/mcd64a1/manifests/ingest_date=2026-11-14/run_id={RUN_ID}.json"


def test_ingest_writes_granules() -> None:
    granules = [_granule("h28v08"), _granule("h28v09")]
    downloader = FakeDownloader({granule.granule_id: b"HDF" for granule in granules})
    store = FakeStore()

    entries, failures = ingest_granules(
        granules,
        downloader=downloader,
        store=store,
        run_id=RUN_ID,
        prefix="bronze/mcd64a1",
    )

    assert failures == []
    assert len(entries) == 2
    assert {entry["action"] for entry in entries} == {"written"}
    assert len(store.objects) == 2


def test_ingest_skips_existing_object() -> None:
    granule = _granule("h28v09")
    store = FakeStore()
    key = object_key("bronze/mcd64a1", granule)
    store.objects[key] = b"lama"
    downloader = FakeDownloader({})

    entries, failures = ingest_granules(
        [granule],
        downloader=downloader,
        store=store,
        run_id=RUN_ID,
        prefix="bronze/mcd64a1",
    )

    assert failures == []
    assert entries[0]["action"] == "skipped"
    assert downloader.calls == []


def test_ingest_isolates_failures() -> None:
    good = _granule("h28v08")
    bad = _granule("h28v09")
    downloader = FakeDownloader({good.granule_id: b"HDF"}, failing={bad.granule_id})
    store = FakeStore()

    entries, failures = ingest_granules(
        [good, bad],
        downloader=downloader,
        store=store,
        run_id=RUN_ID,
        prefix="bronze/mcd64a1",
    )

    assert len(entries) == 1
    assert len(failures) == 1
    assert failures[0].granule_id == bad.granule_id
    assert failures[0].error_type == "DownloadError"


def test_verify_run_passes_when_checksum_matches() -> None:
    granule = _granule("h28v09")
    store = FakeStore()
    downloader = FakeDownloader({granule.granule_id: b"HDF"})
    entries, _ = ingest_granules(
        [granule],
        downloader=downloader,
        store=store,
        run_id=RUN_ID,
        prefix="bronze/mcd64a1",
    )
    store.put_json(manifest_key("bronze/mcd64a1", RUN_ID), {"entries": entries})

    result = verify_run(store, RUN_ID, prefix="bronze/mcd64a1")

    assert result["ok"] is True
    assert result["objects_verified"] == 1


def test_verify_run_detects_tampered_object() -> None:
    granule = _granule("h28v09")
    store = FakeStore()
    downloader = FakeDownloader({granule.granule_id: b"HDF"})
    entries, _ = ingest_granules(
        [granule],
        downloader=downloader,
        store=store,
        run_id=RUN_ID,
        prefix="bronze/mcd64a1",
    )
    store.put_json(manifest_key("bronze/mcd64a1", RUN_ID), {"entries": entries})
    store.objects[object_key("bronze/mcd64a1", granule)] = b"berubah"

    result = verify_run(store, RUN_ID, prefix="bronze/mcd64a1")

    assert result["ok"] is False
    assert result["failures"]


@pytest.mark.parametrize(
    ("written", "failed", "expected"),
    [(1, 0, "success"), (1, 1, "partial"), (0, 1, "failed")],
)
def test_manifest_status(written: int, failed: int, expected: str) -> None:
    from ingest.burned_area.ingest import GranuleFailure, build_manifest

    entries = [
        {
            "granule_id": f"g{index}",
            "month": "2026-09",
            "tile": "h28v09",
            "key": f"key{index}",
            "action": "written",
            "size_bytes": 10,
            "sha256": "x",
        }
        for index in range(written)
    ]
    failures = [
        GranuleFailure(
            granule_id=f"f{index}",
            tile="h28v09",
            error_type="DownloadError",
            message="gagal",
        )
        for index in range(failed)
    ]

    manifest = build_manifest(
        months=["2026-09"],
        entries=entries,
        failures=failures,
        settings=_settings(),
        run_id=RUN_ID,
        started_at="2026-11-14T09:00:00Z",
        finished_at="2026-11-14T09:05:00Z",
    )

    assert manifest["status"] == expected
