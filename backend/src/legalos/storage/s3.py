"""S3-compatible storage backend (SeaweedFS in Docker, a Brazilian AWS region in prod).

Use `legalos.storage.files`, which checks that keys belong to the caller's firm before
delegating here. The bucket is private; files are only reachable through short-lived
signed URLs.
"""

from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from legalos.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


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


def signed_upload_url(key: str, content_type: str) -> str:
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


def signed_download_url(
    key: str,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> str:
    """Short-lived link to view a file inline in the browser."""
    settings = get_settings()
    params = {"Bucket": settings.storage_bucket, "Key": key}
    if content_type:
        params["ResponseContentType"] = content_type
    if filename:
        params["ResponseContentDisposition"] = (
            f"inline; filename*=UTF-8''{quote(filename, safe='')}"
        )
    return _client(public=True).generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.signed_url_ttl_seconds
    )


def object_size(key: str) -> int | None:
    """Size of a stored object in bytes, or None if it does not exist."""
    try:
        head = _client(public=False).head_object(Bucket=get_settings().storage_bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return int(head["ContentLength"])


def delete_object(key: str) -> None:
    _client(public=False).delete_object(Bucket=get_settings().storage_bucket, Key=key)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    """Server-side upload (used by the worker, e.g. for OCR output)."""
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


def get_bytes(key: str) -> bytes:
    obj = _client(public=False).get_object(Bucket=get_settings().storage_bucket, Key=key)
    return obj["Body"].read()
