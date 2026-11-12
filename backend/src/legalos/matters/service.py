"""Clients, matters (processos), parties, team and timeline."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from legalos.audit.service import record
from legalos.core import br_ids, crypto
from legalos.matters.models import Client, Matter, MatterEvent, MatterMember, MatterParty

AREAS = (
    "trabalhista",
    "civel",
    "tributario",
    "consumidor",
    "familia",
    "previdenciario",
    "empresarial",
    "outro",
)
STATUSES = ("ativo", "suspenso", "encerrado", "arquivado")
PARTY_ROLES = (
    "autor",
    "reu",
    "reclamante",
    "reclamada",
    "exequente",
    "executado",
    "terceiro",
    "outro",
)


class MatterError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


# --- Identifiers --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtectedId:
    encrypted: bytes
    hash: str


def protect_document_number(kind: str, value: str) -> ProtectedId:
    """Validate a CPF (PF) or CNPJ (PJ) and return it encrypted plus a lookup hash."""
    if kind == "PF":
        if not br_ids.is_valid_cpf(value):
            raise MatterError("invalid_cpf")
        canonical = br_ids.only_digits(value)
    elif kind == "PJ":
        if not br_ids.is_valid_cnpj(value):
            raise MatterError("invalid_cnpj")
        canonical = br_ids.normalize_cnpj(value)
    else:
        raise MatterError("invalid_kind")
    return ProtectedId(
        encrypted=crypto.encrypt(canonical), hash=crypto.keyed_hash(f"doc:{canonical}")
    )


def reveal_document_number(kind: str, encrypted: bytes | None, *, masked: bool) -> str | None:
    if encrypted is None:
        return None
    value = crypto.decrypt(encrypted)
    if masked:
        return br_ids.mask_document(kind, value)
    return br_ids.format_cpf(value) if kind == "PF" else br_ids.format_cnpj(value)


# --- Timeline -----------------------------------------------------------------------------


def add_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    matter_id: uuid.UUID,
    kind: str,
    summary: str,
    actor_user_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
    source: str = "sistema",
) -> None:
    db.add(
        MatterEvent(
            tenant_id=tenant_id,
            matter_id=matter_id,
            kind=kind,
            summary=summary[:500],
            actor_user_id=actor_user_id,
            payload=payload or {},
            source=source,
        )
    )
    db.flush()


# --- Clients ------------------------------------------------------------------------------


def create_client(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    name: str,
    document_number: str | None,
    email: str | None,
    phone: str | None,
    notes: str | None,
) -> Client:
    protected = protect_document_number(kind, document_number) if document_number else None
    client = Client(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        kind=kind,
        name=name.strip(),
        document_number_encrypted=protected.encrypted if protected else None,
        document_number_hash=protected.hash if protected else None,
        email=email,
        phone=phone,
        notes=notes,
        created_by=user_id,
    )
    db.add(client)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise MatterError("client_already_exists", 409) from e
    record(
        db,
        "client.created",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="client",
        entity_id=str(client.id),
    )
    return client


def list_clients(db: Session, query: str | None = None) -> list[Client]:
    stmt = select(Client).order_by(Client.name).limit(500)
    if query:
        stmt = stmt.where(Client.name.ilike(f"%{_escape_like(query)}%", escape="\\"))
    return list(db.scalars(stmt))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- Matters ------------------------------------------------------------------------------


def create_matter(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    client_id: uuid.UUID,
    title: str,
    cnj_number: str | None,
    area: str,
    court: str | None,
    comarca: str | None,
    vara: str | None,
    description: str | None,
    opened_at: date | None,
) -> Matter:
    if db.get(Client, client_id) is None:
        raise MatterError("client_not_found", 404)
    canonical_cnj = None
    if cnj_number:
        canonical_cnj = br_ids.parse_cnj(cnj_number)
        if canonical_cnj is None:
            raise MatterError("invalid_cnj_number")
    if area not in AREAS:
        raise MatterError("invalid_area")
    matter = Matter(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        client_id=client_id,
        title=title.strip(),
        cnj_number=canonical_cnj,
        area=area,
        court=court,
        comarca=comarca,
        vara=vara,
        description=description,
        opened_at=opened_at,
        created_by=user_id,
    )
    db.add(matter)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise MatterError("matter_already_exists", 409) from e
    db.add(
        MatterMember(
            tenant_id=tenant_id, matter_id=matter.id, user_id=user_id, responsibility="responsavel"
        )
    )
    add_event(
        db,
        tenant_id=tenant_id,
        matter_id=matter.id,
        kind="processo_criado",
        summary="Processo cadastrado",
        actor_user_id=user_id,
        source="manual",
    )
    record(
        db,
        "matter.created",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="matter",
        entity_id=str(matter.id),
    )
    return matter


def list_matters(
    db: Session, *, query: str | None = None, client_id: uuid.UUID | None = None
) -> list[tuple[Matter, Client]]:
    stmt = (
        select(Matter, Client)
        .join(Client, Client.id == Matter.client_id)
        .order_by(Matter.created_at.desc())
        .limit(500)
    )
    if client_id:
        stmt = stmt.where(Matter.client_id == client_id)
    if query:
        like = f"%{_escape_like(query)}%"
        stmt = stmt.where(
            or_(
                Matter.title.ilike(like, escape="\\"),
                Matter.cnj_number.ilike(like, escape="\\"),
                Client.name.ilike(like, escape="\\"),
            )
        )
    return [(m, c) for m, c in db.execute(stmt).all()]


def update_matter(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter: Matter,
    changes: dict[str, Any],
) -> Matter:
    if "status" in changes and changes["status"] not in STATUSES:
        raise MatterError("invalid_status")
    if "area" in changes and changes["area"] not in AREAS:
        raise MatterError("invalid_area")
    if changes.get("cnj_number"):
        canonical = br_ids.parse_cnj(changes["cnj_number"])
        if canonical is None:
            raise MatterError("invalid_cnj_number")
        changes["cnj_number"] = canonical
    old_status = matter.status
    for field, value in changes.items():
        setattr(matter, field, value)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise MatterError("matter_already_exists", 409) from e
    if matter.status != old_status:
        add_event(
            db,
            tenant_id=tenant_id,
            matter_id=matter.id,
            kind="status_alterado",
            summary=f"Situação alterada: {old_status} → {matter.status}",
            actor_user_id=user_id,
            source="manual",
        )
    record(
        db,
        "matter.updated",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="matter",
        entity_id=str(matter.id),
        details={"fields": sorted(changes)},
    )
    return matter


def add_party(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter: Matter,
    name: str,
    role: str,
    kind: str | None,
    is_client: bool,
    document_number: str | None,
) -> MatterParty:
    if role not in PARTY_ROLES:
        raise MatterError("invalid_party_role")
    protected = None
    if document_number:
        if kind is None:
            raise MatterError("invalid_kind")
        protected = protect_document_number(kind, document_number)
    party = MatterParty(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter.id,
        name=name.strip(),
        role=role,
        kind=kind,
        is_client=is_client,
        document_number_encrypted=protected.encrypted if protected else None,
        document_number_hash=protected.hash if protected else None,
    )
    db.add(party)
    db.flush()
    add_event(
        db,
        tenant_id=tenant_id,
        matter_id=matter.id,
        kind="parte_adicionada",
        summary=f"Parte adicionada: {party.name} ({role})",
        actor_user_id=user_id,
        source="manual",
    )
    return party


def add_member(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    matter: Matter,
    user_id: uuid.UUID,
    responsibility: str,
) -> MatterMember:
    if responsibility not in ("responsavel", "equipe"):
        raise MatterError("invalid_responsibility")
    member = db.get(MatterMember, (matter.id, user_id))
    if member is None:
        member = MatterMember(
            tenant_id=tenant_id, matter_id=matter.id, user_id=user_id, responsibility=responsibility
        )
        db.add(member)
    else:
        member.responsibility = responsibility
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        # The composite foreign key refuses users who are not members of this firm.
        raise MatterError("not_a_firm_member", 400) from e
    return member
