"""Write audit events. Every security-relevant action and every read of sensitive data
must go through `record`."""

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.core.db import independent_transaction


def record(
    db: Session,
    action: str,
    *,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an event in the caller's transaction (rolled back if the action fails)."""
    db.execute(
        insert(AuditEvent).values(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip=ip,
            details=details or {},
        )
    )


def record_independently(
    action: str,
    *,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an event that must persist even if the request fails (e.g. a failed login)."""
    with independent_transaction(user_id=actor_user_id, tenant_id=tenant_id) as db:
        record(
            db,
            action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            ip=ip,
            details=details,
        )
