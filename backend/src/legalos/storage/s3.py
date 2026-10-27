"""Object storage for firm files (S3-compatible: SeaweedFS locally, a Brazilian region in prod).

Every object key starts with `tenants/<tenant_id>/`, and signed URLs are only issued for
keys under the caller's own prefix. The bucket itself is private; files are only reachable
through short-lived signed URLs.
"""

import re
import uuid
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from legalos.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


class StorageAccessError(Exception):
    """Raised when a key does not belong to the requesting firm."""


def tenant_prefix(tenant_id: uuid.UUID) -> str:
    return f"tenants/{tenant_id}/"


def object_key(tenant_id: uuid.UUID, *parts: str) -> str:
    """Build a key under the firm's prefix. Parts must be simple names (no '/', no '..')."""
    if not parts:
        raise ValueError("At least one key part is required")
    for part in parts:
        if not _SAFE_PART.match(part) or ".." in part:
            raise ValueError(f"Unsafe key part: {part!r}")
    return tenant_prefix(tenant_id) + "/".join(parts)


def ensure_tenant_key(tenant_id: uuid.UUID, key: str) -> None:
    if not key.startswith(tenant_prefix(tenant_id)) or ".." in key:
        raise StorageAccessError("Key does not belong to this firm")


@lru_cache
def _client(public: bool) -> "S3Client":
    settings = get_settings()
    endpoint = (
        settings.storage_public_endpoint_url or settings.storage_endpoint_url
        if public
        else settings.storage_endpoint_url
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.storage_region,
        aws_access_key_id=settings.storage_access_key.get_secret_value() or None,
        aws_secret_access_key=settings.storage_secret_key.get_secret_value() or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def signed_upload_url(tenant_id: uuid.UUID, key: str, content_type: str) -> str:
    ensure_tenant_key(tenant_id, key)
    settings = get_settings()
    params: dict[str, str] = {
        "Bucket": settings.storage_bucket,
        "Key": key,
        "ContentType": content_type,
    }
    if settings.storage_sse:
        params["ServerSideEncryption"] = settings.storage_sse
    return _client(public=True).generate_presigned_url(
        "put_object", Params=params, ExpiresIn=settings.signed_url_ttl_seconds
    )


def signed_download_url(tenant_id: uuid.UUID, key: str) -> str:
    ensure_tenant_key(tenant_id, key)
    settings = get_settings()
    return _client(public=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.storage_bucket, "Key": key},
        ExpiresIn=settings.signed_url_ttl_seconds,
    )


def put_bytes(tenant_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None:
    """Server-side upload (used by the worker, e.g. for OCR output)."""
    ensure_tenant_key(tenant_id, key)
    settings = get_settings()
    client = _client(public=False)
    if settings.storage_sse:
        client.put_object(
            Bucket=settings.storage_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption=settings.storage_sse,  # type: ignore[arg-type]
        )
    else:
        client.put_object(
            Bucket=settings.storage_bucket, Key=key, Body=data, ContentType=content_type
        )


def get_bytes(tenant_id: uuid.UUID, key: str) -> bytes:
    ensure_tenant_key(tenant_id, key)
    obj = _client(public=False).get_object(Bucket=get_settings().storage_bucket, Key=key)
    return obj["Body"].read()
