import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin


class GatewayCall(TimestampMixin, Base):
    """One AI provider call: what, who, which model, tokens and cost. Never the prompt."""

    __tablename__ = "gateway_calls"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "ai_run_id"], ["ai_runs.tenant_id", "ai_runs.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(100))
