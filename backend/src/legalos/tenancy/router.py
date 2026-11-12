import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.tenancy import service
from legalos.tenancy.models import Membership
from legalos.tenancy.roles import Permission, Role

router = APIRouter(prefix="/api/firm", tags=["firm"])


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    oab: str | None = None


class MemberIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    role: Role
    oab_number: str | None = Field(default=None, max_length=20)
    oab_uf: str | None = Field(default=None, min_length=2, max_length=2)


class MemberAddedOut(BaseModel):
    user_id: uuid.UUID
    # Shown once. None when the person already had a LegalOS account (they keep their
    # own password).
    temporary_password: str | None


class RoleIn(BaseModel):
    role: Role


@router.get("/members")
def list_members(
    principal: Annotated[Principal, Depends(require(Permission.VIEW_MEMBERS))], db: DbSession
) -> list[MemberOut]:
    # RLS already hides other firms' members. The firm filter is still needed because RLS
    # also lets a user see their *own* memberships in other firms (for the firm switcher).
    rows = db.execute(
        select(User.id, User.name, User.email, Membership.role, User.oab_number, User.oab_uf)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == principal.tenant_id)
        .order_by(User.name)
    ).all()
    return [
        MemberOut(
            user_id=r.id,
            name=r.name,
            email=r.email,
            role=r.role,
            oab=f"OAB/{r.oab_uf} {r.oab_number}" if r.oab_number else None,
        )
        for r in rows
    ]


TeamManager = Annotated[Principal, Depends(require(Permission.MANAGE_MEMBERS))]


def _raise(e: service.TeamError) -> None:
    raise HTTPException(e.status_code, e.code) from e


@router.post("/members", status_code=201)
def add_member(
    body: MemberIn, request: Request, principal: TeamManager, db: DbSession
) -> MemberAddedOut:
    assert principal.tenant_id is not None
    try:
        added = service.add_member(
            db,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            ip=client_ip(request),
            **body.model_dump(),
        )
    except service.TeamError as e:
        _raise(e)
    return MemberAddedOut(user_id=added.user_id, temporary_password=added.temporary_password)


@router.patch("/members/{user_id}", status_code=204)
def change_role(
    user_id: uuid.UUID, body: RoleIn, request: Request, principal: TeamManager, db: DbSession
) -> None:
    assert principal.tenant_id is not None
    try:
        service.change_role(
            db,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            user_id=user_id,
            role=body.role,
            ip=client_ip(request),
        )
    except service.TeamError as e:
        _raise(e)


@router.delete("/members/{user_id}", status_code=204)
def remove_member(
    user_id: uuid.UUID, request: Request, principal: TeamManager, db: DbSession
) -> None:
    assert principal.tenant_id is not None
    try:
        service.remove_member(
            db,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            user_id=user_id,
            ip=client_ip(request),
        )
    except service.TeamError as e:
        _raise(e)
