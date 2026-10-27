import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base


class AuditEvent(Base):
    """Append-only audit record. The app role may only INSERT and SELECT this table."""

    __tablename__ = "audit_log"
    # No INSERT ... RETURNING: events without a firm (e.g. failed logins) may be written
    # but are deliberately not readable by the app role, and RETURNING would require that.
    __table_args__ = {"implicit_returning": False}  # noqa: RUF012

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Null for events before a firm is known (e.g. a failed login).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
