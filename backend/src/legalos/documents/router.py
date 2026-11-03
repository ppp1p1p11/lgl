import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.service import Principal
from legalos.documents import service
from legalos.documents.models import Document, DocumentVersion
from legalos.matters.router import get_matter_or_404
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api", tags=["documents"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_MATTERS))]
Uploader = Annotated[Principal, Depends(require(Permission.MANAGE_DOCUMENTS))]

VersionStatus = Literal["pending_upload", "uploaded", "processing", "ready", "failed", "rejected"]


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_type: str = Field(max_length=150)
    size_bytes: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=300)


class UploadTicketOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    upload_url: str
    # The browser must send exactly this Content-Type header with the PUT.
    content_type: str


class VersionOut(BaseModel):
    id: uuid.UUID
    version_no: int
    original_filename: str
    detected_type: str | None
    size_bytes: int | None
    page_count: int | None
    ocr_page_count: int | None
    min_ocr_confidence: float | None
    low_ocr_confidence: bool
    status: VersionStatus
    error_code: str | None
    created_at: datetime
    processed_at: datetime | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    matter_id: uuid.UUID
    title: str
    doc_class: str | None
    created_at: datetime
    current_version: VersionOut | None
    latest_version: VersionOut


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class PageOut(BaseModel):
    page_number: int
    text: str
    method: Literal["text_layer", "ocr", "docx"]
    ocr_confidence: float | None
    low_ocr_confidence: bool


class FileUrlOut(BaseModel):
    url: str
    content_type: str | None


class SearchHitOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    page_number: int
    # Matches are wrapped in U+0002 ... U+0003 (not HTML).
    snippet: str


def _low(confidence: float | None) -> bool:
    return confidence is not None and confidence < service.LOW_OCR_CONFIDENCE


def _version_out(v: DocumentVersion) -> VersionOut:
    return VersionOut(
        id=v.id,
        version_no=v.version_no,
        original_filename=v.original_filename,
        detected_type=v.detected_type,
        size_bytes=v.size_bytes,
        page_count=v.page_count,
        ocr_page_count=v.ocr_page_count,
        min_ocr_confidence=v.min_ocr_confidence,
        low_ocr_confidence=_low(v.min_ocr_confidence),
        status=v.status,
        error_code=v.error_code,
        created_at=v.created_at,
        processed_at=v.processed_at,
    )


def _versions(db: DbSession, document_id: uuid.UUID) -> list[DocumentVersion]:
    return list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        )
    )


def _document_out(d: Document, versions: list[DocumentVersion]) -> DocumentOut:
    current = next((v for v in versions if v.id == d.current_version_id), None)
    return DocumentOut(
        id=d.id,
        matter_id=d.matter_id,
        title=d.title,
        doc_class=d.doc_class,
        created_at=d.created_at,
        current_version=_version_out(current) if current else None,
        latest_version=_version_out(versions[0]),
    )


def _raise(e: service.DocumentError) -> None:
    raise HTTPException(e.status_code, e.code) from e


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    assert principal.tenant_id is not None
    return principal.tenant_id, principal.user_id


def _get_version(db: DbSession, version_id: uuid.UUID) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "document_not_found")
    return version


@router.get("/matters/{matter_id}/documents")
def list_documents(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> list[DocumentOut]:
    get_matter_or_404(db, matter_id)
    docs = db.scalars(
        select(Document).where(Document.matter_id == matter_id).order_by(Document.created_at.desc())
    )
    return [_document_out(d, _versions(db, d.id)) for d in docs]


@router.post("/matters/{matter_id}/documents", status_code=201)
def start_upload(
    matter_id: uuid.UUID, body: UploadRequest, principal: Uploader, db: DbSession
) -> UploadTicketOut:
    tenant_id, user_id = _ids(principal)
    get_matter_or_404(db, matter_id)
    try:
        ticket = service.start_upload(
            db, tenant_id=tenant_id, user_id=user_id, matter_id=matter_id, **body.model_dump()
        )
    except service.DocumentError as e:
        _raise(e)
    return UploadTicketOut(**ticket.__dict__)


@router.post("/documents/{document_id}/versions", status_code=201)
def start_new_version(
    document_id: uuid.UUID, body: UploadRequest, principal: Uploader, db: DbSession
) -> UploadTicketOut:
    tenant_id, user_id = _ids(principal)
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "document_not_found")
    try:
        ticket = service.start_new_version(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            document=document,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except service.DocumentError as e:
        _raise(e)
    return UploadTicketOut(**ticket.__dict__)


@router.post("/document-versions/{version_id}/complete")
def complete_upload(version_id: uuid.UUID, principal: Uploader, db: DbSession) -> VersionOut:
    tenant_id, user_id = _ids(principal)
    version = _get_version(db, version_id)
    try:
        service.complete_upload(db, tenant_id=tenant_id, user_id=user_id, version=version)
    except service.DocumentError as e:
        _raise(e)
    return _version_out(version)


@router.get("/documents/{document_id}")
def get_document(document_id: uuid.UUID, _: Viewer, db: DbSession) -> DocumentDetail:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "document_not_found")
    versions = _versions(db, document.id)
    return DocumentDetail(
        **_document_out(document, versions).model_dump(),
        versions=[_version_out(v) for v in versions],
    )


@router.get("/document-versions/{version_id}/pages")
def get_pages(
    version_id: uuid.UUID, request: Request, principal: Viewer, db: DbSession
) -> list[PageOut]:
    tenant_id, user_id = _ids(principal)
    version = _get_version(db, version_id)
    pages = service.read_pages(
        db, tenant_id=tenant_id, user_id=user_id, version=version, ip=client_ip(request)
    )
    return [
        PageOut(
            page_number=p.page_number,
            text=p.text,
            method=p.method,
            ocr_confidence=p.ocr_confidence,
            low_ocr_confidence=_low(p.ocr_confidence),
        )
        for p in pages
    ]


@router.get("/document-versions/{version_id}/file-url")
def get_file_url(
    version_id: uuid.UUID, request: Request, principal: Viewer, db: DbSession
) -> FileUrlOut:
    tenant_id, user_id = _ids(principal)
    version = _get_version(db, version_id)
    try:
        url = service.file_url(
            db, tenant_id=tenant_id, user_id=user_id, version=version, ip=client_ip(request)
        )
    except service.DocumentError as e:
        _raise(e)
    return FileUrlOut(url=url, content_type=version.detected_type)


@router.get("/matters/{matter_id}/search")
def search(
    matter_id: uuid.UUID,
    request: Request,
    principal: Viewer,
    db: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=200)],
) -> list[SearchHitOut]:
    tenant_id, user_id = _ids(principal)
    get_matter_or_404(db, matter_id)
    hits = service.search_matter(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        matter_id=matter_id,
        query=q,
        ip=client_ip(request),
    )
    return [
        SearchHitOut(
            document_id=h.document_id,
            document_title=h.document_title,
            version_id=h.version_id,
            page_number=h.page_number,
            snippet=h.snippet,
        )
        for h in hits
    ]
