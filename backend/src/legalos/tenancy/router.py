import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from legalos.auth.deps import DbSession, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.tenancy.models import Membership
from legalos.tenancy.roles import Permission, Role

router = APIRouter(prefix="/api/firm", tags=["firm"])


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: Role


@router.get("/members")
def list_members(
    principal: Annotated[Principal, Depends(require(Permission.VIEW_MEMBERS))], db: DbSession
) -> list[MemberOut]:
    # RLS already hides other firms' members. The firm filter is still needed because RLS
    # also lets a user see their *own* memberships in other firms (for the firm switcher).
    rows = db.execute(
        select(User.id, User.name, User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == principal.tenant_id)
        .order_by(User.name)
    ).all()
    return [MemberOut(user_id=r.id, name=r.name, email=r.email, role=r.role) for r in rows]
