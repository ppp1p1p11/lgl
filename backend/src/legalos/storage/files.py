"""Storage of firm files, with two interchangeable backends.

- "s3": S3-compatible object storage (Docker setup, production in a Brazilian region).
- "local": a folder on disk, for running the app on a laptop without Docker. Signed
  links point to the API itself (`storage/router.py`).

Every object key starts with `tenants/<tenant_id>/`, and every function here checks that
the key belongs to the caller's firm before touching the backend.
"""

import re
import uuid
from types import ModuleType

from legalos.config import get_settings

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


def _backend() -> ModuleType:
    if get_settings().storage_backend == "local":
        from legalos.storage import local

        return local
    from legalos.storage import s3

    return s3


def signed_upload_url(tenant_id: uuid.UUID, key: str, content_type: str) -> str:
    ensure_tenant_key(tenant_id, key)
    url: str = _backend().signed_upload_url(key, content_type)
    return url


def signed_download_url(
    tenant_id: uuid.UUID,
    key: str,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> str:
    """Short-lived link to view a file inline in the browser."""
    ensure_tenant_key(tenant_id, key)
    url: str = _backend().signed_download_url(key, content_type=content_type, filename=filename)
    return url


def object_size(tenant_id: uuid.UUID, key: str) -> int | None:
    """Size of a stored object in bytes, or None if it does not exist."""
    ensure_tenant_key(tenant_id, key)
    size: int | None = _backend().object_size(key)
    return size


def delete_object(tenant_id: uuid.UUID, key: str) -> None:
    ensure_tenant_key(tenant_id, key)
    _backend().delete_object(key)


def put_bytes(tenant_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None:
    """Server-side upload (used by the worker)."""
    ensure_tenant_key(tenant_id, key)
    _backend().put_bytes(key, data, content_type)


def get_bytes(tenant_id: uuid.UUID, key: str) -> bytes:
    ensure_tenant_key(tenant_id, key)
    data: bytes = _backend().get_bytes(key)
    return data
