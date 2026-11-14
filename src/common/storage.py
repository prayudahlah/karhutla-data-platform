"""S3-compatible Bronze storage backed by Garage."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from common.config import GarageSettings

logger = logging.getLogger(__name__)

JSON_INDENT = 2


class BronzeStorageError(RuntimeError):
    """Base error for Bronze storage operations."""


class ObjectNotFoundError(BronzeStorageError):
    """Raised when an object does not exist in the Bronze bucket."""


class ObjectAlreadyExistsError(BronzeStorageError):
    """Raised when an ingestion attempt would overwrite an existing object."""


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _is_not_found(exc: ClientError) -> bool:
    return _error_code(exc) in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


def serialize_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=JSON_INDENT).encode("utf-8")


def serialize_jsonl(records: Iterable[Any]) -> bytes:
    """Satu objek JSON per baris, tanpa indentasi. Dipakai batch event stream."""
    return b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for record in records
    )


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BronzeStore:
    """Small, explicit S3 client tailored to Garage's S3-compatible API.

    The client always uses path-style addressing and SigV4, which Garage
    requires for local endpoint URLs. Checksum calculation is left to the SDK
    only when required so S3-compatible servers do not reject unknown headers.
    """

    def __init__(
        self,
        settings: GarageSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.bucket = settings.bucket
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: GarageSettings) -> Any:
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.force_path_style else "auto"},
            connect_timeout=settings.connect_timeout,
            read_timeout=settings.read_timeout,
            retries={"max_attempts": settings.max_attempts, "mode": "standard"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        return boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            config=config,
        )

    @property
    def client(self) -> Any:
        return self._client

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            logger.info("Garage bucket is reachable: %s", self.bucket)
            return
        except ClientError as exc:
            if not _is_not_found(exc):
                raise BronzeStorageError(
                    f"Cannot access Garage bucket {self.bucket!r}: {exc}"
                ) from exc

        try:
            self._client.create_bucket(Bucket=self.bucket)
            logger.info("Created Garage bucket: %s", self.bucket)
        except ClientError as exc:
            code = _error_code(exc)
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                return
            raise BronzeStorageError(
                f"Bucket {self.bucket!r} does not exist and could not be created. "
                "Create it with: garage bucket create <bucket>"
            ) from exc
        except BotoCoreError as exc:
            raise BronzeStorageError(
                f"Bucket {self.bucket!r} does not exist and could not be created: {exc}"
            ) from exc

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise BronzeStorageError(f"Cannot check object {key!r}: {exc}") from exc

    def head_object(self, key: str) -> dict[str, Any]:
        try:
            return self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(f"Object not found: s3://{self.bucket}/{key}") from exc
            raise BronzeStorageError(f"Cannot head object {key!r}: {exc}") from exc

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        """Upload body apa adanya. Dipakai put_json dan put_jsonl."""
        digest = sha256_hex(body)
        object_metadata = {"sha256": digest}
        if metadata:
            object_metadata.update(metadata)

        if not overwrite and self.object_exists(key):
            raise ObjectAlreadyExistsError(
                f"Refusing to overwrite existing Bronze object: s3://{self.bucket}/{key}"
            )

        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=object_metadata,
            )
        except (ClientError, BotoCoreError) as exc:
            raise BronzeStorageError(f"Failed to upload {key!r}: {exc}") from exc

        logger.info("Uploaded s3://%s/%s (%d bytes)", self.bucket, key, len(body))
        return digest

    def put_json(
        self,
        key: str,
        payload: Any,
        *,
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        return self.put_bytes(
            key,
            serialize_json(payload),
            content_type="application/json",
            metadata=metadata,
            overwrite=overwrite,
        )

    def put_jsonl(
        self,
        key: str,
        records: Iterable[Any],
        *,
        metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        return self.put_bytes(
            key,
            serialize_jsonl(records),
            content_type="application/x-ndjson",
            metadata=metadata,
            overwrite=overwrite,
        )

    def read_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(f"Object not found: s3://{self.bucket}/{key}") from exc
            raise BronzeStorageError(f"Failed to read {key!r}: {exc}") from exc
        except BotoCoreError as exc:
            raise BronzeStorageError(f"Failed to read {key!r}: {exc}") from exc

    def read_json(self, key: str) -> Any:
        body = self.read_bytes(key)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BronzeStorageError(f"Object {key!r} is not valid UTF-8 JSON") from exc

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    keys.append(item["Key"])
        except (ClientError, BotoCoreError) as exc:
            raise BronzeStorageError(f"Failed to list prefix {prefix!r}: {exc}") from exc
        return keys

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise BronzeStorageError(f"Failed to delete {key!r}: {exc}") from exc

    def readback_sha256(self, key: str) -> str:
        return sha256_hex(self.read_bytes(key))
