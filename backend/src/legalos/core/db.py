"""Database engine, sessions, and the per-transaction tenant context.

Tenant isolation is enforced by PostgreSQL Row-Level Security (ADR-0002). The policies
read two transaction-local settings, `app.user_id` and `app.tenant_id`, which this module
sets with `set_config(..., is_local => true)`. They are reset automatically when the
transaction ends, so a pooled connection never carries one request's tenant into the next.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, Engine, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from legalos.config import get_settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True, pool_size=10)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def set_db_context(
    db: Session, *, user_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None
) -> None:
    """Set who is acting for the rest of the current transaction.

    Must be called inside a transaction. Values never come from request input directly:
    only from an authenticated session or a job row.
    """
    db.execute(
        text(
            "SELECT set_config('app.user_id', :user_id, true),"
            " set_config('app.tenant_id', :tenant_id, true)"
        ),
        {
            "user_id": str(user_id) if user_id else "",
            "tenant_id": str(tenant_id) if tenant_id else "",
        },
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one transaction per request, committed if the handler succeeds."""
    with get_sessionmaker()() as db, db.begin():
        yield db


@contextmanager
def independent_transaction(
    *, user_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None
) -> Iterator[Session]:
    """A separate transaction, committed as soon as the block ends.

    Used for records that must survive even if the request's own transaction rolls back,
    such as failed-login audit events and throttling counters.
    """
    with get_sessionmaker()() as db, db.begin():
        set_db_context(db, user_id=user_id, tenant_id=tenant_id)
        yield db
