import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from legalos.audit.models import AuditEvent
from legalos.audit.service import record
from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.service import Principal
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api/audit-log", tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]


@router.get("")
def list_audit_events(
    request: Request,
    principal: Annotated[Principal, Depends(require(Permission.VIEW_AUDIT_LOG))],
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventOut]:
    events = db.scalars(
        select(AuditEvent)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
    record(
        db,
        "audit_log.read",
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        ip=client_ip(request),
    )
    return [
        AuditEventOut(
            id=e.id,
            occurred_at=e.occurred_at,
            actor_user_id=e.actor_user_id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            details=e.details,
        )
        for e in events
    ]
