import os
import uuid
from urllib.parse import urlparse

import pytest
from pydantic import SecretStr

from legalos.storage.s3 import (
    StorageAccessError,
    object_key,
    signed_download_url,
    signed_upload_url,
)

A, B = uuid.uuid4(), uuid.uuid4()


def test_keys_are_prefixed_by_firm() -> None:
    assert object_key(A, "docs", "peticao.pdf") == f"tenants/{A}/docs/peticao.pdf"


@pytest.mark.parametrize("part", ["../x", "a/b", "", ".hidden", "x" * 300])
def test_unsafe_key_parts_rejected(part: str) -> None:
    with pytest.raises(ValueError):
        object_key(A, part)


def test_cannot_sign_another_firms_key() -> None:
    key_b = object_key(B, "docs", "contrato.pdf")
    with pytest.raises(StorageAccessError):
        signed_download_url(A, key_b)
    with pytest.raises(StorageAccessError):
        signed_upload_url(A, key_b, "application/pdf")
    with pytest.raises(StorageAccessError):
        signed_download_url(A, f"tenants/{A}/../{B}/docs/contrato.pdf")


def test_signed_url_is_short_lived_and_scoped() -> None:
    url = signed_download_url(A, object_key(A, "docs", "peticao.pdf"))
    parsed = urlparse(url)
    assert parsed.path == f"/legalos-documents/tenants/{A}/docs/peticao.pdf"
    assert "X-Amz-Expires=300" in parsed.query


@pytest.mark.skipif(
    not os.environ.get("LEGALOS_TEST_S3_ENDPOINT"),
    reason="set LEGALOS_TEST_S3_ENDPOINT to run against a real S3-compatible server",
)
def test_round_trip_against_real_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from legalos.config import get_settings
    from legalos.storage import bootstrap, s3

    endpoint = os.environ["LEGALOS_TEST_S3_ENDPOINT"]
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_endpoint_url", endpoint)
    monkeypatch.setattr(settings, "storage_access_key", SecretStr("legalos-dev"))
    monkeypatch.setattr(settings, "storage_secret_key", SecretStr("legalos-dev-secret"))
    s3._client.cache_clear()
    try:
        bootstrap.main()
        key = object_key(A, "docs", "teste.txt")
        put = httpx.put(
            signed_upload_url(A, key, "text/plain"),
            content=b"conteudo",
            headers={"Content-Type": "text/plain"},
        )
        assert put.status_code == 200
        assert httpx.get(signed_download_url(A, key)).content == b"conteudo"
        # Without a signature the bucket refuses access.
        assert httpx.get(f"{endpoint}/{settings.storage_bucket}/{key}").status_code == 403
    finally:
        s3._client.cache_clear()
