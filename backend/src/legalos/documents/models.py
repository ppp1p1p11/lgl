import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    doc_class: Mapped[str | None] = mapped_column(String(50))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class DocumentVersion(TimestampMixin, Base):
    """One uploaded file. Files are immutable: a new upload is a new version."""

    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(300))
    declared_content_type: Mapped[str | None] = mapped_column(String(150))
    detected_type: Mapped[str | None] = mapped_column(String(20))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_page_count: Mapped[int | None] = mapped_column(Integer)
    min_ocr_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="pending_upload")
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(Base):
    """Extracted text of one page. Untrusted content: never treated as instructions."""

    __tablename__ = "document_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)


class DocumentChunk(TimestampMixin, Base):
    """A searchable passage of one page, with its exact position in that page's text:
    `page.text[char_start:char_end] == chunk.text`. Citations in Phase 2b point here.

    The embedding dimension and ANN index are fixed when the embedding model is chosen
    (docs/VERIFY.md AI-3).
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    page_number: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('portuguese', text)", persisted=True), deferred=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
