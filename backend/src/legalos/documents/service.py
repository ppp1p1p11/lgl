"""Document upload, processing and reading.

Upload flow (the file never passes through the API):
1. `start_upload` creates the document version and a short-lived signed PUT URL.
2. The browser sends the file straight to object storage.
3. `complete_upload` checks the object exists and is within limits, then enqueues
   `documents.process`.
4. The worker detects the real file type, extracts per-page text (OCR when needed),
   splits it into chunks, and marks the version ready.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from legalos.audit.service import record
from legalos.documents import extraction, filetypes
from legalos.documents.chunking import chunk_page
from legalos.documents.models import Document, DocumentChunk, DocumentPage, DocumentVersion
from legalos.jobs.models import Job
from legalos.jobs.queue import enqueue, handler
from legalos.matters.service import add_event
from legalos.storage import s3

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Pages whose OCR confidence is below this are flagged "texto pode conter erros".
LOW_OCR_CONFIDENCE = 70.0
ALLOWED_DECLARED_TYPES = set(filetypes.CONTENT_TYPES.values())


class DocumentError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class UploadTicket:
    document_id: uuid.UUID
    version_id: uuid.UUID
    upload_url: str
    content_type: str


def _validate_declared(filename: str, content_type: str, size_bytes: int) -> None:
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise DocumentError("file_too_large" if size_bytes > 0 else "file_empty")
    if content_type not in ALLOWED_DECLARED_TYPES:
        raise DocumentError("unsupported_type")
    if not filename.strip():
        raise DocumentError("filename_required")


def _new_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    document: Document,
    filename: str,
    content_type: str,
    user_id: uuid.UUID,
) -> UploadTicket:
    next_no = (
        db.scalar(
            select(func.max(DocumentVersion.version_no)).where(
                DocumentVersion.document_id == document.id
            )
        )
        or 0
    ) + 1
    version_id = uuid.uuid4()
    key = s3.object_key(tenant_id, "documents", str(document.id), str(version_id))
    db.add(
        DocumentVersion(
            id=version_id,
            tenant_id=tenant_id,
            document_id=document.id,
            version_no=next_no,
            storage_key=key,
            original_filename=filename.strip()[:300],
            declared_content_type=content_type,
            created_by=user_id,
        )
    )
    db.flush()
    return UploadTicket(
        document_id=document.id,
        version_id=version_id,
        upload_url=s3.signed_upload_url(tenant_id, key, content_type),
        content_type=content_type,
    )


def start_upload(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter_id: uuid.UUID,
    title: str | None,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> UploadTicket:
    _validate_declared(filename, content_type, size_bytes)
    document = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter_id,
        title=(title or filename).strip()[:300],
        created_by=user_id,
    )
    db.add(document)
    db.flush()
    return _new_version(
        db,
        tenant_id=tenant_id,
        document=document,
        filename=filename,
        content_type=content_type,
        user_id=user_id,
    )


def start_new_version(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    document: Document,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> UploadTicket:
    _validate_declared(filename, content_type, size_bytes)
    return _new_version(
        db,
        tenant_id=tenant_id,
        document=document,
        filename=filename,
        content_type=content_type,
        user_id=user_id,
    )


def complete_upload(
    db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, version: DocumentVersion
) -> None:
    """Called after the browser finished uploading. Oversized files are rejected (a signed
    PUT URL cannot limit size by itself)."""
    if version.status != "pending_upload":
        raise DocumentError("upload_already_completed", 409)
    size = s3.object_size(tenant_id, version.storage_key)
    if size is None:
        raise DocumentError("upload_not_found", 409)
    if size > MAX_UPLOAD_BYTES:
        s3.delete_object(tenant_id, version.storage_key)
        version.status, version.error_code = "rejected", "file_too_large"
        return
    version.size_bytes = size
    version.status = "uploaded"
    enqueue(
        db,
        "documents.process",
        tenant_id=tenant_id,
        enqueued_by=user_id,
        payload={"version_id": str(version.id)},
        max_attempts=3,
    )
    document = db.get(Document, version.document_id)
    assert document is not None
    add_event(
        db,
        tenant_id=tenant_id,
        matter_id=document.matter_id,
        kind="documento_enviado",
        summary=f"Documento enviado: {document.title}",
        actor_user_id=user_id,
        payload={"document_id": str(document.id), "version_no": version.version_no},
    )


# --- Processing (worker) ------------------------------------------------------------------


@handler("documents.process")
def process_version(db: Session, job: Job) -> None:
    version = db.get(DocumentVersion, uuid.UUID(job.payload["version_id"]))
    if version is None or version.status not in ("uploaded", "processing", "failed"):
        return  # already processed, rejected, or removed
    try:
        with db.begin_nested():
            _process(db, version)
    except Exception:
        if job.attempts < job.max_attempts:
            raise  # the queue retries with backoff
        # Last attempt: record the failure so the document does not look queued forever.
        db.refresh(version)
        _finish(db, version, status="failed", error_code="processing_error")


def _process(db: Session, version: DocumentVersion) -> None:
    tenant_id = version.tenant_id
    version.status = "processing"

    data = s3.get_bytes(tenant_id, version.storage_key)
    version.size_bytes = len(data)
    version.sha256 = hashlib.sha256(data).hexdigest()
    detected = filetypes.sniff(data)
    version.detected_type = detected
    if detected is None:
        # Not a file type we accept, whatever its name says. Do not keep it.
        s3.delete_object(tenant_id, version.storage_key)
        _finish(db, version, status="rejected", error_code="unsupported_type")
        return

    try:
        pages = extraction.extract(data, detected)
    except extraction.ExtractionError as e:
        _finish(db, version, status="failed", error_code=e.code)
        return

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_version_id == version.id))
    for page in pages:
        db.add(
            DocumentPage(
                tenant_id=tenant_id,
                document_version_id=version.id,
                page_number=page.page_number,
                text=page.text,
                method=page.method,
                ocr_confidence=page.ocr_confidence,
            )
        )
        for chunk in chunk_page(page.text):
            db.add(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_version_id=version.id,
                    page_number=page.page_number,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    text=chunk.text,
                )
            )
    # An OCR page without any recognized word counts as confidence 0.
    ocr_scores = [p.ocr_confidence or 0.0 for p in pages if p.method == "ocr"]
    version.page_count = len(pages)
    version.ocr_page_count = len(ocr_scores)
    version.min_ocr_confidence = min(ocr_scores) if ocr_scores else None
    _finish(db, version, status="ready", error_code=None)


def _finish(db: Session, version: DocumentVersion, *, status: str, error_code: str | None) -> None:
    version.status = status
    version.error_code = error_code
    version.processed_at = datetime.now(UTC)
    document = db.get(Document, version.document_id)
    assert document is not None
    if status == "ready":
        # The newest ready version becomes the current one.
        current = (
            db.get(DocumentVersion, document.current_version_id)
            if document.current_version_id
            else None
        )
        if current is None or current.version_no < version.version_no:
            document.current_version_id = version.id
    summaries = {
        "ready": f"Documento processado: {document.title}",
        "failed": f"Não foi possível ler o documento: {document.title}",
        "rejected": f"Arquivo recusado (tipo não suportado): {document.title}",
    }
    db.flush()
    add_event(
        db,
        tenant_id=version.tenant_id,
        matter_id=document.matter_id,
        kind=f"documento_{status}",
        summary=summaries[status],
        actor_user_id=None,
        payload={
            "document_id": str(document.id),
            "version_no": version.version_no,
            "error_code": error_code,
        },
    )


# --- Reading ------------------------------------------------------------------------------


def read_pages(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    version: DocumentVersion,
    ip: str | None,
) -> list[DocumentPage]:
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_version_id == version.id)
            .order_by(DocumentPage.page_number)
        )
    )
    record(
        db,
        "document.text_read",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="document_version",
        entity_id=str(version.id),
        ip=ip,
    )
    return pages


def file_url(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    version: DocumentVersion,
    ip: str | None,
) -> str:
    if version.status in ("pending_upload", "rejected"):
        raise DocumentError("file_not_available", 409)
    record(
        db,
        "document.file_opened",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="document_version",
        entity_id=str(version.id),
        ip=ip,
    )
    content_type = filetypes.CONTENT_TYPES.get(version.detected_type or "", None)
    return s3.signed_download_url(
        tenant_id,
        version.storage_key,
        content_type=content_type or version.declared_content_type,
        filename=version.original_filename,
    )


# --- Search -------------------------------------------------------------------------------

HIGHLIGHT_START = "\u0002"
HIGHLIGHT_END = "\u0003"


@dataclass(frozen=True)
class SearchHit:
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    page_number: int
    snippet: str
    rank: float


def search_matter(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter_id: uuid.UUID,
    query: str,
    ip: str | None,
    limit: int = 30,
) -> list[SearchHit]:
    """Full-text search (Portuguese) over the current version of each document.

    Snippets mark matches with control characters (not HTML), so document text can never
    inject markup into the page.
    """
    rows = db.execute(
        text(
            """
            WITH q AS (SELECT websearch_to_tsquery('portuguese', :query) AS query)
            SELECT d.id AS document_id, d.title, c.document_version_id AS version_id,
                   c.page_number,
                   ts_headline('portuguese', c.text, q.query,
                       'StartSel=' || chr(2) || ', StopSel=' || chr(3)
                       || ', MaxWords=35, MinWords=12, MaxFragments=2') AS snippet,
                   ts_rank(c.tsv, q.query) AS rank
            FROM document_chunks c
            JOIN documents d ON d.current_version_id = c.document_version_id
            CROSS JOIN q
            WHERE d.matter_id = :matter_id AND c.tsv @@ q.query
            ORDER BY rank DESC, d.title, c.page_number
            LIMIT :limit
            """
        ),
        {"query": query, "matter_id": matter_id, "limit": limit},
    ).all()
    record(
        db,
        "matter.searched",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="matter",
        entity_id=str(matter_id),
        ip=ip,
        details={"query": query[:200], "results": len(rows)},
    )
    return [
        SearchHit(
            document_id=r.document_id,
            document_title=r.title,
            version_id=r.version_id,
            page_number=r.page_number,
            snippet=r.snippet,
            rank=float(r.rank),
        )
        for r in rows
    ]
