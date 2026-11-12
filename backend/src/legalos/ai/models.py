import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class AiRun(TimestampMixin, Base):
    """One execution of an AI workflow: the auditable trace linked to the matter."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    workflow: Mapped[str] = mapped_column(String(30))
    # What was asked: the research question, the draft's template and instructions…
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(50))
    started_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiOutput(TimestampMixin, Base):
    """An AI draft (facts or summary). Consequential use requires an approved version."""

    __tablename__ = "ai_outputs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "ai_run_id"], ["ai_runs.tenant_id", "ai_runs.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ai_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="rascunho")
    current_version_no: Mapped[int] = mapped_column(Integer, default=1)


class AiOutputVersion(TimestampMixin, Base):
    """Immutable content of one version of an AI output."""

    __tablename__ = "ai_output_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ai_output_id"], ["ai_outputs.tenant_id", "ai_outputs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    ai_output_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by_ai: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)


class AiCitation(Base):
    """Where a fact or summary passage comes from, and whether that was verified."""

    __tablename__ = "ai_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ai_output_version_id"],
            ["ai_output_versions.tenant_id", "ai_output_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    ai_output_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    item_index: Mapped[int] = mapped_column(Integer)
    # Exactly one target: a firm document or a legal corpus unit version.
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    legal_unit_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_unit_versions.id")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    quoted_text: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String(20))


class AiApproval(Base):
    """A lawyer's decision on one specific version. Append-only."""

    __tablename__ = "ai_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ai_output_version_id"],
            ["ai_output_versions.tenant_id", "ai_output_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_user_id"], ["memberships.tenant_id", "memberships.user_id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    ai_output_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approver_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
