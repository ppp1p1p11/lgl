"""The local-folder storage backend used to run the app without Docker."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from legalos.config import get_settings
from legalos.storage import files, local


@pytest.fixture
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_local_dir", str(tmp_path))
    return tmp_path


def test_round_trip_through_signed_links(client: TestClient, local_storage: Path) -> None:
    tenant = uuid.uuid4()
    key = files.object_key(tenant, "documents", "a", "b")
    upload_url = files.signed_upload_url(tenant, key, "application/pdf")
    assert upload_url.startswith("/api/storage/objects/")

    r = client.put(upload_url, content=b"%PDF-1.7 test", headers={"Content-Type": "text/html"})
    assert r.status_code == 403  # must match the type the link was issued for
    r = client.put(
        upload_url, content=b"%PDF-1.7 test", headers={"Content-Type": "application/pdf"}
    )
    assert r.status_code == 200
    assert files.object_size(tenant, key) == len(b"%PDF-1.7 test")
    assert (local_storage / key).read_bytes() == b"%PDF-1.7 test"

    download_url = files.signed_download_url(
        tenant, key, content_type="application/pdf", filename="petição.pdf"
    )
    r = client.get(download_url)
    assert r.status_code == 200 and r.content == b"%PDF-1.7 test"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert "peti%C3%A7%C3%A3o.pdf" in r.headers["content-disposition"]

    # An upload link cannot be used to download, and vice versa.
    assert client.get(upload_url).status_code == 403
    assert client.put(download_url.split("?")[0], content=b"x").status_code == 403

    files.delete_object(tenant, key)
    assert files.object_size(tenant, key) is None


def test_tampered_or_expired_links_are_refused(
    client: TestClient, local_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, other = uuid.uuid4(), uuid.uuid4()
    files.put_bytes(other, files.object_key(other, "secret"), b"de outro escritorio", "text/plain")
    token = local.sign({"op": "get", "key": files.object_key(tenant, "x"), "ct": None})
    signature = token.split(".")[1]
    forged_body = local.sign({"op": "get", "key": files.object_key(other, "secret")}).split(".")[0]
    assert client.get(f"/api/storage/objects/{forged_body}.{signature}").status_code == 403
    assert client.get("/api/storage/objects/garbage").status_code == 403

    monkeypatch.setattr(get_settings(), "signed_url_ttl_seconds", -1)
    expired = files.signed_download_url(tenant, files.object_key(tenant, "x"))
    assert client.get(expired).status_code == 403


def test_keys_cannot_escape_the_storage_folder(local_storage: Path) -> None:
    with pytest.raises(local.InvalidTokenError):
        local.path_for("../../etc/passwd")


def test_oversized_upload_is_cut_off(
    client: TestClient, local_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from legalos.storage import router

    monkeypatch.setattr(router, "MAX_UPLOAD_BYTES", 10)
    tenant = uuid.uuid4()
    key = files.object_key(tenant, "big")
    url = files.signed_upload_url(tenant, key, "application/pdf")
    r = client.put(url, content=b"x" * 100, headers={"Content-Type": "application/pdf"})
    assert r.status_code == 413
    assert files.object_size(tenant, key) is None


def test_routes_are_disabled_with_s3_backend(client: TestClient) -> None:
    assert client.get("/api/storage/objects/anything").status_code == 404
