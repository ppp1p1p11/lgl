import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(300))
    document_number_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_number_hash: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Matter(TimestampMixin, Base):
    """A processo (or a pre-litigation matter, without a CNJ number)."""

    __tablename__ = "matters"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "client_id"], ["clients.tenant_id", "clients.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    cnj_number: Mapped[str | None] = mapped_column(String(25))
    area: Mapped[str] = mapped_column(String(30))
    court: Mapped[str | None] = mapped_column(String(50))
    comarca: Mapped[str | None] = mapped_column(String(120))
    vara: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    description: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class MatterParty(TimestampMixin, Base):
    __tablename__ = "matter_parties"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str | None] = mapped_column(String(2))
    role: Mapped[str] = mapped_column(String(30))
    is_client: Mapped[bool] = mapped_column(Boolean, default=False)
    document_number_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_number_hash: Mapped[str | None] = mapped_column(String(64))


class MatterMember(TimestampMixin, Base):
    __tablename__ = "matter_members"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["memberships.tenant_id", "memberships.user_id"]
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    responsibility: Mapped[str] = mapped_column(String(20), default="equipe")


class MatterEvent(Base):
    """Timeline entry. Append-only for the app."""

    __tablename__ = "matter_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20), default="sistema")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    summary: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
