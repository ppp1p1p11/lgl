import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from legalos.core.db import Base, TimestampMixin
from legalos.tenancy.roles import Role


class Tenant(TimestampMixin, Base):
    """An escritório (law firm)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    # AI policy, set by a sócio.
    ai_monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(50))
    ai_redaction_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="member_role", values_callable=lambda e: [m.value for m in e])
    )
