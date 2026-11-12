import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class HolidayRow(TimestampMixin, Base):
    """A day without court business. tenant_id NULL = national (system) holiday."""

    __tablename__ = "holidays"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    day: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), default="feriado")
    scope: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class DeadlineProposal(TimestampMixin, Base):
    __tablename__ = "deadline_proposals"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    rule_set: Mapped[str] = mapped_column(String(10))
    preset_id: Mapped[str | None] = mapped_column(String(50))
    trigger_kind: Mapped[str] = mapped_column(String(30))
    trigger_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(20))
    doubled_reason: Mapped[str | None] = mapped_column(String(30))
    proposed_date: Mapped[date] = mapped_column(Date)
    reasoning: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="proposto")
    confirmed_date: Mapped[date | None] = mapped_column(Date)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "matter_id"], ["matters.tenant_id", "matters.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "deadline_proposal_id"],
            ["deadline_proposals.tenant_id", "deadline_proposals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignee_user_id"], ["memberships.tenant_id", "memberships.user_id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    matter_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="aberta")
    origin: Mapped[str] = mapped_column(String(20), default="manual")
    deadline_proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
