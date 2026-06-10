"""Object storage behind an interface (S3 API; MinIO in development).

The interface keeps the cloud-provider decision (Open Decision #4) open:
any S3-compatible store works, and a different provider can be certified
behind the same protocol later.
"""

from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import get_settings


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...


class S3ObjectStorage:
    """S3-compatible object storage (MinIO locally)."""

    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.object_storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="eu-west-2",
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()


class MemoryObjectStorage:
    """In-memory storage for tests and offline development."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]


_storage_override: ObjectStorage | None = None


def set_object_storage(storage: ObjectStorage | None) -> None:
    """Override the storage backend (tests and offline development only)."""
    global _storage_override
    _storage_override = storage


def get_object_storage() -> ObjectStorage:
    if _storage_override is not None:
        return _storage_override
    return S3ObjectStorage()
