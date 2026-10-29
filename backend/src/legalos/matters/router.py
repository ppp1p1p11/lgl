import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from legalos.audit.service import record
from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.matters import service
from legalos.matters.models import Client, Matter, MatterEvent, MatterMember, MatterParty
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api", tags=["matters"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_MATTERS))]
Manager = Annotated[Principal, Depends(require(Permission.MANAGE_CLIENTS))]

PersonKind = Literal["PF", "PJ"]
Area = Literal[
    "trabalhista",
    "civel",
    "tributario",
    "consumidor",
    "familia",
    "previdenciario",
    "empresarial",
    "outro",
]
Status = Literal["ativo", "suspenso", "encerrado", "arquivado"]
PartyRole = Literal[
    "autor",
    "reu",
    "reclamante",
    "reclamada",
    "exequente",
    "executado",
    "terceiro",
    "outro",
]


def _raise(e: service.MatterError) -> None:
    raise HTTPException(e.status_code, e.code) from e


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    assert principal.tenant_id is not None
    return principal.tenant_id, principal.user_id


# --- Clients ------------------------------------------------------------------------------


class ClientIn(BaseModel):
    kind: PersonKind
    name: str = Field(min_length=2, max_length=300)
    document_number: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=5000)


class ClientOut(BaseModel):
    id: uuid.UUID
    kind: PersonKind
    name: str
    document_number: str | None  # masked in lists, full in the detail view
    email: str | None
    phone: str | None
    created_at: datetime


def _client_out(c: Client, *, masked: bool) -> ClientOut:
    return ClientOut(
        id=c.id,
        kind=c.kind,
        name=c.name,
        document_number=service.reveal_document_number(
            c.kind, c.document_number_encrypted, masked=masked
        ),
        email=c.email,
        phone=c.phone,
        created_at=c.created_at,
    )


@router.get("/clients")
def list_clients(
    _: Viewer, db: DbSession, q: Annotated[str | None, Query(max_length=100)] = None
) -> list[ClientOut]:
    return [_client_out(c, masked=True) for c in service.list_clients(db, q)]


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, principal: Manager, db: DbSession) -> ClientOut:
    tenant_id, user_id = _ids(principal)
    try:
        client = service.create_client(
            db, tenant_id=tenant_id, user_id=user_id, **body.model_dump()
        )
    except service.MatterError as e:
        _raise(e)
    return _client_out(client, masked=True)


@router.get("/clients/{client_id}")
def get_client(
    client_id: uuid.UUID, request: Request, principal: Viewer, db: DbSession
) -> ClientOut:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client_not_found")
    tenant_id, user_id = _ids(principal)
    if client.document_number_encrypted:
        record(
            db,
            "client.identifier_read",
            tenant_id=tenant_id,
            actor_user_id=user_id,
            entity_type="client",
            entity_id=str(client.id),
            ip=client_ip(request),
        )
    return _client_out(client, masked=False)


# --- Matters ------------------------------------------------------------------------------


class MatterIn(BaseModel):
    client_id: uuid.UUID
    title: str = Field(min_length=3, max_length=300)
    cnj_number: str | None = Field(default=None, max_length=30)
    area: Area
    court: str | None = Field(default=None, max_length=50)
    comarca: str | None = Field(default=None, max_length=120)
    vara: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    opened_at: date | None = None


class MatterPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    cnj_number: str | None = Field(default=None, max_length=30)
    area: Area | None = None
    court: str | None = Field(default=None, max_length=50)
    comarca: str | None = Field(default=None, max_length=120)
    vara: str | None = Field(default=None, max_length=200)
    status: Status | None = None
    description: str | None = Field(default=None, max_length=5000)


class MatterSummary(BaseModel):
    id: uuid.UUID
    title: str
    cnj_number: str | None
    area: Area
    court: str | None
    status: Status
    client_id: uuid.UUID
    client_name: str
    created_at: datetime


class PartyIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    role: PartyRole
    kind: PersonKind | None = None
    is_client: bool = False
    document_number: str | None = Field(default=None, max_length=30)


class PartyOut(BaseModel):
    id: uuid.UUID
    name: str
    role: PartyRole
    kind: PersonKind | None
    is_client: bool
    document_number: str | None  # always masked


class MemberIn(BaseModel):
    user_id: uuid.UUID
    responsibility: Literal["responsavel", "equipe"] = "equipe"


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    responsibility: Literal["responsavel", "equipe"]


class MatterDetail(MatterSummary):
    comarca: str | None
    vara: str | None
    description: str | None
    opened_at: date | None
    parties: list[PartyOut]
    members: list[MemberOut]


class EventOut(BaseModel):
    id: uuid.UUID
    kind: str
    source: str
    summary: str
    actor_user_id: uuid.UUID | None
    occurred_at: datetime


def _summary(m: Matter, c: Client) -> MatterSummary:
    return MatterSummary(
        id=m.id,
        title=m.title,
        cnj_number=m.cnj_number,
        area=m.area,
        court=m.court,
        status=m.status,
        client_id=c.id,
        client_name=c.name,
        created_at=m.created_at,
    )


def get_matter_or_404(db: DbSession, matter_id: uuid.UUID) -> Matter:
    # RLS makes another firm's matter indistinguishable from a missing one.
    matter = db.get(Matter, matter_id)
    if matter is None:
        raise HTTPException(404, "matter_not_found")
    return matter


def _detail(db: DbSession, matter: Matter) -> MatterDetail:
    client = db.get(Client, matter.client_id)
    assert client is not None
    parties = db.scalars(
        select(MatterParty)
        .where(MatterParty.matter_id == matter.id)
        .order_by(MatterParty.created_at)
    )
    members = db.execute(
        select(MatterMember, User.name)
        .join(User, User.id == MatterMember.user_id)
        .where(MatterMember.matter_id == matter.id)
        .order_by(User.name)
    ).all()
    base = _summary(matter, client)
    return MatterDetail(
        **base.model_dump(),
        comarca=matter.comarca,
        vara=matter.vara,
        description=matter.description,
        opened_at=matter.opened_at,
        parties=[
            PartyOut(
                id=p.id,
                name=p.name,
                role=p.role,
                kind=p.kind,
                is_client=p.is_client,
                document_number=service.reveal_document_number(
                    p.kind or "PF", p.document_number_encrypted, masked=True
                ),
            )
            for p in parties
        ],
        members=[
            MemberOut(user_id=mm.user_id, name=name, responsibility=mm.responsibility)
            for mm, name in members
        ],
    )


@router.get("/matters")
def list_matters(
    _: Viewer,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    client_id: uuid.UUID | None = None,
) -> list[MatterSummary]:
    return [_summary(m, c) for m, c in service.list_matters(db, query=q, client_id=client_id)]


@router.post("/matters", status_code=201)
def create_matter(body: MatterIn, principal: Manager, db: DbSession) -> MatterDetail:
    tenant_id, user_id = _ids(principal)
    try:
        matter = service.create_matter(
            db, tenant_id=tenant_id, user_id=user_id, **body.model_dump()
        )
    except service.MatterError as e:
        _raise(e)
    return _detail(db, matter)


@router.get("/matters/{matter_id}")
def get_matter(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> MatterDetail:
    return _detail(db, get_matter_or_404(db, matter_id))


@router.patch("/matters/{matter_id}")
def update_matter(
    matter_id: uuid.UUID, body: MatterPatch, principal: Manager, db: DbSession
) -> MatterDetail:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        service.update_matter(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            matter=matter,
            changes=body.model_dump(exclude_unset=True),
        )
    except service.MatterError as e:
        _raise(e)
    return _detail(db, matter)


@router.post("/matters/{matter_id}/parties", status_code=201)
def add_party(
    matter_id: uuid.UUID, body: PartyIn, principal: Manager, db: DbSession
) -> MatterDetail:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        service.add_party(
            db, tenant_id=tenant_id, user_id=user_id, matter=matter, **body.model_dump()
        )
    except service.MatterError as e:
        _raise(e)
    return _detail(db, matter)


@router.delete("/matters/{matter_id}/parties/{party_id}")
def remove_party(
    matter_id: uuid.UUID, party_id: uuid.UUID, principal: Manager, db: DbSession
) -> MatterDetail:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    party = db.get(MatterParty, party_id)
    if party is None or party.matter_id != matter.id:
        raise HTTPException(404, "party_not_found")
    db.delete(party)
    db.flush()
    service.add_event(
        db,
        tenant_id=tenant_id,
        matter_id=matter.id,
        kind="parte_removida",
        summary=f"Parte removida: {party.name}",
        actor_user_id=user_id,
        source="manual",
    )
    return _detail(db, matter)


@router.put("/matters/{matter_id}/members")
def set_member(
    matter_id: uuid.UUID, body: MemberIn, principal: Manager, db: DbSession
) -> MatterDetail:
    tenant_id, _user = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        service.add_member(
            db,
            tenant_id=tenant_id,
            matter=matter,
            user_id=body.user_id,
            responsibility=body.responsibility,
        )
    except service.MatterError as e:
        _raise(e)
    return _detail(db, matter)


@router.get("/matters/{matter_id}/events")
def list_events(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> list[EventOut]:
    get_matter_or_404(db, matter_id)
    events = db.scalars(
        select(MatterEvent)
        .where(MatterEvent.matter_id == matter_id)
        .order_by(MatterEvent.occurred_at.desc())
        .limit(500)
    )
    return [
        EventOut(
            id=e.id,
            kind=e.kind,
            source=e.source,
            summary=e.summary,
            actor_user_id=e.actor_user_id,
            occurred_at=e.occurred_at,
        )
        for e in events
    ]
