import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class DocumentChunk(TimestampMixin, Base):
    """A searchable piece of a firm document.

    Phase 1 keeps only what the tenant-isolation tests need. Phase 2 links chunks to
    document versions and page spans; the embedding dimension and index are fixed when
    the embedding model is chosen (docs/VERIFY.md AI-3).
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
