"""Team management by a sócio: add people, change roles, remove from the firm.

There is no e-mail service yet (it is an external API, added later), so a new account
gets a temporary password that is shown once to the sócio, who passes it on. The person
must change it and set up MFA on first login.
"""

import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from legalos.audit.service import record
from legalos.auth.models import User
from legalos.core import crypto
from legalos.tenancy.models import Membership
from legalos.tenancy.roles import Role


class TeamError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AddedMember:
    user_id: uuid.UUID
    temporary_password: str | None  # None when the person already had an account


def add_member(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    email: str,
    name: str,
    role: Role,
    oab_number: str | None,
    oab_uf: str | None,
    ip: str | None,
) -> AddedMember:
    email = email.strip().lower()
    existing = db.execute(text("SELECT id FROM auth_lookup_user(:email)"), {"email": email}).first()
    temporary_password = None
    if existing is not None:
        user_id: uuid.UUID = existing.id
        if db.get(Membership, (tenant_id, user_id)) is not None:
            raise TeamError("already_a_member", 409)
    else:
        user_id = uuid.uuid4()
        temporary_password = secrets.token_urlsafe(12)
        # Plain INSERT (no RETURNING): the new row is not readable until the membership
        # below exists.
        db.execute(
            insert(User).values(
                id=user_id,
                email=email,
                name=name.strip(),
                password_hash=crypto.hash_password(temporary_password),
                oab_number=oab_number,
                oab_uf=oab_uf.upper() if oab_uf else None,
                is_active=True,
                must_change_password=True,
            )
        )
    db.add(Membership(tenant_id=tenant_id, user_id=user_id, role=role))
    db.flush()
    record(
        db,
        "firm.member_added",
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=str(user_id),
        ip=ip,
        details={"role": role.value},
    )
    return AddedMember(user_id=user_id, temporary_password=temporary_password)


def _socio_count(db: Session, tenant_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.role == Role.SOCIO)
        )
        or 0
    )


def _membership(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    membership = db.get(Membership, (tenant_id, user_id))
    if membership is None:
        raise TeamError("member_not_found", 404)
    return membership


def change_role(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
    ip: str | None,
) -> None:
    membership = _membership(db, tenant_id, user_id)
    if membership.role == Role.SOCIO and role != Role.SOCIO and _socio_count(db, tenant_id) <= 1:
        raise TeamError("last_socio", 409)
    old = membership.role
    membership.role = role
    db.flush()
    record(
        db,
        "firm.member_role_changed",
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=str(user_id),
        ip=ip,
        details={"from": Role(old).value, "to": role.value},
    )


def remove_member(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    user_id: uuid.UUID,
    ip: str | None,
) -> None:
    if user_id == actor_user_id:
        raise TeamError("cannot_remove_yourself", 409)
    membership = _membership(db, tenant_id, user_id)
    if membership.role == Role.SOCIO and _socio_count(db, tenant_id) <= 1:
        raise TeamError("last_socio", 409)
    db.delete(membership)
    db.flush()
    record(
        db,
        "firm.member_removed",
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=str(user_id),
        ip=ip,
    )
