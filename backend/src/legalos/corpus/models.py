import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Date, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class IngestionRun(Base):
    __tablename__ = "corpus_ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="running")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LegalDocument(TimestampMixin, Base):
    """One law, súmula collection, or decision. Global: shared by all firms."""

    __tablename__ = "legal_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    doc_type: Mapped[str] = mapped_column(String(30))
    identifier: Mapped[str] = mapped_column(String(200), unique=True)
    short_name: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(500))
    issuing_body: Mapped[str | None] = mapped_column(String(200))
    urn: Mapped[str | None] = mapped_column(String(300))
    publication_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    review_status: Mapped[str] = mapped_column(String(40), default="oficial")


class LegalUnit(Base):
    """A structural unit: artigo, parágrafo, inciso, alínea, enunciado…"""

    __tablename__ = "legal_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    legal_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_documents.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("legal_units.id"))
    unit_type: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(200))
    heading_path: Mapped[str | None] = mapped_column(String(1000))
    position: Mapped[int] = mapped_column(Integer)


class LegalUnitVersion(TimestampMixin, Base):
    """The text of a unit during a period of validity."""

    __tablename__ = "legal_unit_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    legal_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_units.id"))
    text: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="vigente")
    amendment_note: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corpus_ingestion_runs.id")
    )
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('portuguese', text)", persisted=True), deferred=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), deferred=True)
