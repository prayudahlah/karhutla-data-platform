from __future__ import annotations

import io
from typing import Any

import pytest
from botocore.exceptions import ClientError

from common.config import GarageSettings
from common.storage import (
    BronzeStore,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    serialize_json,
    sha256_hex,
)


def _client_error(code: str, operation: str = "HeadObject") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        operation,
    )


class FakePaginator:
    def __init__(self, client: FakeS3Client) -> None:
        self.client = client

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        keys = [
            {"Key": key}
            for (bucket, key) in sorted(self.client.objects)
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return [{"Contents": keys}]


class FakeS3Client:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}

    def head_bucket(self, *, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise _client_error("404", "HeadBucket")

    def create_bucket(self, *, Bucket: str) -> None:
        self.buckets.add(Bucket)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        item = self.objects.get((Bucket, Key))
        if item is None:
            raise _client_error("404")
        return {
            "ContentLength": len(item["body"]),
            "Metadata": item["metadata"],
            "ContentType": item["content_type"],
        }

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> None:
        self.objects[(Bucket, Key)] = {
            "body": Body,
            "content_type": ContentType,
            "metadata": Metadata,
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        item = self.objects.get((Bucket, Key))
        if item is None:
            raise _client_error("NoSuchKey", "GetObject")
        return {"Body": io.BytesIO(item["body"])}

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self)


def _settings() -> GarageSettings:
    return GarageSettings(
        endpoint="http://127.0.0.1:3900",
        region="garage",
        access_key_id="test",
        secret_access_key="test",
        bucket="lakehouse",
        prefix="bronze/open_meteo",
    )


def _store() -> tuple[BronzeStore, FakeS3Client]:
    client = FakeS3Client()
    return BronzeStore(_settings(), client=client), client


def test_ensure_bucket_creates_missing_bucket() -> None:
    store, client = _store()

    store.ensure_bucket()

    assert client.buckets == {"lakehouse"}


def test_put_json_writes_metadata_and_reads_back() -> None:
    store, client = _store()
    payload = {"hello": "world", "value": 1}

    digest = store.put_json("bronze/a.json", payload, metadata={"run-id": "run-1"})

    assert digest == sha256_hex(serialize_json(payload))
    assert store.object_exists("bronze/a.json")
    assert store.read_json("bronze/a.json") == payload
    assert store.readback_sha256("bronze/a.json") == digest
    metadata = client.objects[("lakehouse", "bronze/a.json")]["metadata"]
    assert metadata["sha256"] == digest
    assert metadata["run-id"] == "run-1"


def test_put_json_refuses_overwrite_by_default() -> None:
    store, _ = _store()
    store.put_json("bronze/a.json", {"value": 1})

    with pytest.raises(ObjectAlreadyExistsError):
        store.put_json("bronze/a.json", {"value": 2})

    assert store.read_json("bronze/a.json") == {"value": 1}


def test_put_json_can_overwrite_explicitly() -> None:
    store, _ = _store()
    store.put_json("bronze/a.json", {"value": 1})

    store.put_json("bronze/a.json", {"value": 2}, overwrite=True)

    assert store.read_json("bronze/a.json") == {"value": 2}


def test_missing_object_and_listing() -> None:
    store, _ = _store()

    with pytest.raises(ObjectNotFoundError):
        store.read_json("bronze/missing.json")

    store.put_json("bronze/a/one.json", {"n": 1})
    store.put_json("bronze/a/two.json", {"n": 2})
    store.put_json("bronze/b/three.json", {"n": 3})

    assert store.list_keys("bronze/a/") == ["bronze/a/one.json", "bronze/a/two.json"]
