from __future__ import annotations

import uuid

import pytest

from common.config import ConfigError, Settings
from common.storage import BronzeStore, sha256_hex

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    try:
        return Settings.from_env()
    except ConfigError as exc:
        pytest.skip(f"Garage environment is not configured: {exc}")


def test_garage_put_head_readback_and_delete() -> None:
    settings = _settings()
    store = BronzeStore(settings.garage)
    store.ensure_bucket()

    key = f"{settings.garage.prefix}/_integration/{uuid.uuid4().hex}.json"
    payload = {"source": "integration-test", "value": 42}

    try:
        digest = store.put_json(key, payload, metadata={"kind": "integration"})
        assert store.object_exists(key)

        head = store.head_object(key)
        assert int(head["ContentLength"]) > 0

        body = store.read_bytes(key)
        assert sha256_hex(body) == digest
        assert store.read_json(key) == payload
        assert store.readback_sha256(key) == digest
        assert store.object_exists(key)

        keys = store.list_keys(f"{settings.garage.prefix}/_integration/")
        assert key in keys
    finally:
        if store.object_exists(key):
            store.delete_object(key)

    assert not store.object_exists(key)
