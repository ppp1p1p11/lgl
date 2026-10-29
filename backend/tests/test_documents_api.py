"""Upload -> processing -> reading -> search, with an in-memory fake of object storage.
`test_storage.py` covers the real S3-compatible server."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.documents.models import DocumentChunk, DocumentPage
from legalos.jobs.queue import run_one
from legalos.storage import s3
from legalos.tenancy.roles import Role
from tests.conftest import login_with_mfa
from tests.corpus.generator import build_corpus, render_docx, render_pdf, render_scan

PDF = "application/pdf"
DOCS = build_corpus()


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_via_signed_url(self, url: str, data: bytes) -> None:
        key = url.split("fake-storage/", 1)[1]
        self.objects[key] = data


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()

    def upload_url(tenant_id, key, content_type):  # type: ignore[no-untyped-def]
        s3.ensure_tenant_key(tenant_id, key)
        return f"http://fake-storage/{key}"

    def download_url(tenant_id, key, **kwargs):  # type: ignore[no-untyped-def]
        s3.ensure_tenant_key(tenant_id, key)
        return f"http://fake-storage/{key}?download"

    def size(tenant_id, key):  # type: ignore[no-untyped-def]
        s3.ensure_tenant_key(tenant_id, key)
        return len(fake.objects[key]) if key in fake.objects else None

    def get(tenant_id, key):  # type: ignore[no-untyped-def]
        s3.ensure_tenant_key(tenant_id, key)
        return fake.objects[key]

    def delete(tenant_id, key):  # type: ignore[no-untyped-def]
        s3.ensure_tenant_key(tenant_id, key)
        fake.objects.pop(key, None)

    monkeypatch.setattr(s3, "signed_upload_url", upload_url)
    monkeypatch.setattr(s3, "signed_download_url", download_url)
    monkeypatch.setattr(s3, "object_size", size)
    monkeypatch.setattr(s3, "get_bytes", get)
    monkeypatch.setattr(s3, "delete_object", delete)
    return fake


@pytest.fixture
def matter(client: TestClient, make_firm, make_member) -> dict:
    m = make_member(make_firm("Alfa"), Role.ADVOGADO)
    login_with_mfa(client, m.email)
    c = client.post("/api/clients", json={"kind": "PF", "name": "Cliente"}).json()
    return client.post(
        "/api/matters", json={"client_id": c["id"], "title": "Ação de cobrança", "area": "civel"}
    ).json()


def upload(
    client: TestClient,
    storage: FakeStorage,
    matter_id: str,
    data: bytes,
    filename: str = "doc.pdf",
    content_type: str = PDF,
    title: str | None = None,
) -> dict:
    r = client.post(
        f"/api/matters/{matter_id}/documents",
        json={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(data),
            "title": title,
        },
    )
    assert r.status_code == 201, r.text
    ticket = r.json()
    storage.put_via_signed_url(ticket["upload_url"], data)
    r = client.post(f"/api/document-versions/{ticket['version_id']}/complete")
    assert r.status_code == 200, r.text
    return ticket


def run_worker() -> None:
    while run_one("test-worker"):
        pass


def test_upload_process_read_and_search(client, storage, matter, owner_engine: Engine) -> None:
    contestacao, sentenca = DOCS[1], DOCS[2]
    t1 = upload(client, storage, matter["id"], render_pdf(contestacao), title="Contestação")
    t2 = upload(
        client,
        storage,
        matter["id"],
        render_scan(sentenca, "good"),
        filename="sentenca-escaneada.pdf",
        title="Sentença",
    )
    docs = client.get(f"/api/matters/{matter['id']}/documents").json()
    assert {d["latest_version"]["status"] for d in docs} == {"uploaded"}

    run_worker()

    docs = {d["id"]: d for d in client.get(f"/api/matters/{matter['id']}/documents").json()}
    digital = docs[t1["document_id"]]["current_version"]
    scanned = docs[t2["document_id"]]["current_version"]
    assert digital["status"] == "ready" and digital["ocr_page_count"] == 0
    assert scanned["status"] == "ready" and scanned["ocr_page_count"] == 1
    assert scanned["low_ocr_confidence"] is False

    pages = client.get(f"/api/document-versions/{t2['version_id']}/pages").json()
    assert pages[0]["method"] == "ocr" and "IMPROCEDENTE" in pages[0]["text"]

    # Every chunk points at its exact place in the page text.
    with Session(owner_engine) as db:
        for chunk in db.scalars(select(DocumentChunk)):
            page = db.get(DocumentPage, (chunk.document_version_id, chunk.page_number))
            assert page is not None
            assert page.text[chunk.char_start : chunk.char_end] == chunk.text

    hits = client.get(f"/api/matters/{matter['id']}/search", params={"q": "transferências"}).json()
    assert hits and hits[0]["document_id"] == t1["document_id"]
    assert "\u0002" in hits[0]["snippet"] and "<b>" not in hits[0]["snippet"]
    # Portuguese stemming: "improcedência" (contestação) and "improcedente" (sentença).
    titles = {
        h["document_title"]
        for h in client.get(
            f"/api/matters/{matter['id']}/search", params={"q": "improcedente"}
        ).json()
    }
    assert titles == {"Contestação", "Sentença"}

    url = client.get(f"/api/document-versions/{t1['version_id']}/file-url").json()["url"]
    assert url.startswith("http://fake-storage/tenants/")

    events = [e["kind"] for e in client.get(f"/api/matters/{matter['id']}/events").json()]
    assert events.count("documento_ready") == 2 and events.count("documento_enviado") == 2
    with Session(owner_engine) as db:
        actions = set(db.scalars(select(AuditEvent.action)))
    assert {"document.text_read", "document.file_opened", "matter.searched"} <= actions


def test_new_version_becomes_current(client, storage, matter) -> None:
    first = upload(client, storage, matter["id"], render_pdf(DOCS[0]))
    run_worker()
    r = client.post(
        f"/api/documents/{first['document_id']}/versions",
        json={
            "filename": "v2.docx",
            "size_bytes": 10,
            "content_type": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
        },
    )
    second = r.json()
    storage.put_via_signed_url(second["upload_url"], render_docx(DOCS[0]))
    client.post(f"/api/document-versions/{second['version_id']}/complete")
    run_worker()
    detail = client.get(f"/api/documents/{first['document_id']}").json()
    assert detail["current_version"]["id"] == second["version_id"]
    assert [v["version_no"] for v in detail["versions"]] == [2, 1]
    assert detail["current_version"]["detected_type"] == "docx"
    # Search covers only the current version, so the document appears once.
    hits = client.get(f"/api/matters/{matter['id']}/search", params={"q": "horas extras"}).json()
    assert {h["version_id"] for h in hits} == {second["version_id"]}


def test_file_with_fake_extension_is_rejected_and_deleted(client, storage, matter) -> None:
    ticket = upload(
        client,
        storage,
        matter["id"],
        b"<html><script>alert(1)</script></html>",
        filename="peticao.pdf",
    )
    run_worker()
    version = client.get(f"/api/documents/{ticket['document_id']}").json()["latest_version"]
    assert version["status"] == "rejected" and version["error_code"] == "unsupported_type"
    assert storage.objects == {}
    r = client.get(f"/api/document-versions/{ticket['version_id']}/file-url")
    assert r.status_code == 409


def test_upload_limits(client, storage, matter) -> None:
    r = client.post(
        f"/api/matters/{matter['id']}/documents",
        json={"filename": "x.exe", "content_type": "application/x-msdownload", "size_bytes": 10},
    )
    assert r.json() == {"detail": "unsupported_type"}
    r = client.post(
        f"/api/matters/{matter['id']}/documents",
        json={"filename": "big.pdf", "content_type": PDF, "size_bytes": 60 * 1024 * 1024},
    )
    assert r.json() == {"detail": "file_too_large"}

    # The browser declared a small file but uploaded a huge one: rejected at completion.
    r = client.post(
        f"/api/matters/{matter['id']}/documents",
        json={"filename": "liar.pdf", "content_type": PDF, "size_bytes": 10},
    )
    ticket = r.json()
    storage.put_via_signed_url(ticket["upload_url"], b"%PDF-" + b"0" * (51 * 1024 * 1024))
    version = client.post(f"/api/document-versions/{ticket['version_id']}/complete").json()
    assert version["status"] == "rejected" and version["error_code"] == "file_too_large"
    assert storage.objects == {}


def test_complete_requires_an_uploaded_file_and_only_once(client, storage, matter) -> None:
    r = client.post(
        f"/api/matters/{matter['id']}/documents",
        json={"filename": "a.pdf", "content_type": PDF, "size_bytes": 10},
    )
    version_id = r.json()["version_id"]
    assert client.post(f"/api/document-versions/{version_id}/complete").json() == {
        "detail": "upload_not_found"
    }
    storage.put_via_signed_url(r.json()["upload_url"], render_pdf(DOCS[1]))
    assert client.post(f"/api/document-versions/{version_id}/complete").status_code == 200
    assert client.post(f"/api/document-versions/{version_id}/complete").status_code == 409


def test_encrypted_pdf_fails_with_reason(client, storage, matter) -> None:
    import io

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, encrypt="senha")
    c.drawString(100, 700, "x")
    c.showPage()
    c.save()
    ticket = upload(client, storage, matter["id"], buffer.getvalue())
    run_worker()
    version = client.get(f"/api/documents/{ticket['document_id']}").json()["latest_version"]
    assert (version["status"], version["error_code"]) == ("failed", "pdf_encrypted")


def test_other_firm_cannot_read_documents(client, storage, matter, make_firm, make_member) -> None:
    ticket = upload(client, storage, matter["id"], render_pdf(DOCS[1]))
    run_worker()
    client.post("/api/auth/logout")
    outsider = make_member(make_firm("Beta"))
    login_with_mfa(client, outsider.email)
    assert client.get(f"/api/documents/{ticket['document_id']}").status_code == 404
    assert client.get(f"/api/document-versions/{ticket['version_id']}/pages").status_code == 404
    assert client.get(f"/api/document-versions/{ticket['version_id']}/file-url").status_code == 404
    assert (
        client.get(
            f"/api/matters/{matter['id']}/search", params={"q": "transferências"}
        ).status_code
        == 404
    )
    r = client.post(f"/api/document-versions/{ticket['version_id']}/complete")
    assert r.status_code == 404


def test_storage_errors_are_retried_then_marked_failed(
    client, storage, matter, monkeypatch: pytest.MonkeyPatch, owner_engine: Engine
) -> None:
    from sqlalchemy import text

    ticket = upload(client, storage, matter["id"], render_pdf(DOCS[1]))

    def broken(tenant_id, key):  # type: ignore[no-untyped-def]
        raise ConnectionError("storage down")

    monkeypatch.setattr(s3, "get_bytes", broken)
    for _ in range(3):
        run_worker()
        with Session(owner_engine) as db, db.begin():
            db.execute(text("UPDATE jobs SET run_after = now()"))
    version = client.get(f"/api/documents/{ticket['document_id']}").json()["latest_version"]
    assert (version["status"], version["error_code"]) == ("failed", "processing_error")


def test_unknown_version_is_404(client, storage, matter) -> None:
    assert client.get(f"/api/document-versions/{uuid.uuid4()}/pages").status_code == 404
    assert time.time() > 0


def test_worker_entrypoint_resolves_all_models() -> None:
    """The worker does not import the API routers; every model must still be mapped."""
    import subprocess
    import sys

    code = (
        "import legalos.worker\n"
        "from legalos.core.db import Base\n"
        "for table in Base.metadata.tables.values():\n"
        "    for fk in table.foreign_keys:\n"
        "        fk.column  # raises NoReferencedTableError if a model was never imported\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
