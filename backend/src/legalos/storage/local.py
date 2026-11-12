"""Local-folder storage backend, for running the app on a laptop without Docker.

Files live under `LEGALOS_STORAGE_LOCAL_DIR`. Instead of S3 signed URLs, the API issues
short-lived links signed with HMAC (`/api/storage/objects/<token>`), served by
`storage/router.py`. Never use this backend in production: files are not encrypted at
rest by the app and are served by the API process.
"""

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from legalos.config import get_settings

ROUTE_PREFIX = "/api/storage/objects/"


class InvalidTokenError(Exception):
    pass


def _root() -> Path:
    return Path(get_settings().storage_local_dir).resolve()


def path_for(key: str) -> Path:
    """Map a key to a file under the storage folder, refusing anything that escapes it."""
    root = _root()
    path = (root / key).resolve()
    if root not in path.parents:
        raise InvalidTokenError("Key outside the storage folder")
    return path


def _secret() -> bytes:
    key = get_settings().encryption_key.get_secret_value().encode()
    return hashlib.sha256(b"legalos-local-storage:" + key).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(claims: dict[str, Any]) -> str:
    claims = {**claims, "exp": int(time.time()) + get_settings().signed_url_ttl_seconds}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify(token: str, operation: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise InvalidTokenError("bad signature")
        claims: dict[str, Any] = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError) as e:
        raise InvalidTokenError("malformed token") from e
    if claims.get("op") != operation or claims.get("exp", 0) < time.time():
        raise InvalidTokenError("expired or wrong operation")
    return claims


def signed_upload_url(key: str, content_type: str) -> str:
    return ROUTE_PREFIX + sign({"op": "put", "key": key, "ct": content_type})


def signed_download_url(
    key: str, *, content_type: str | None = None, filename: str | None = None
) -> str:
    claims: dict[str, Any] = {"op": "get", "key": key, "ct": content_type}
    if filename:
        claims["fn"] = filename
    return ROUTE_PREFIX + sign(claims) + (f"?f={quote(filename)}" if filename else "")


def object_size(key: str) -> int | None:
    path = path_for(key)
    return path.stat().st_size if path.is_file() else None


def delete_object(key: str) -> None:
    path_for(key).unlink(missing_ok=True)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    path = path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def get_bytes(key: str) -> bytes:
    return path_for(key).read_bytes()
