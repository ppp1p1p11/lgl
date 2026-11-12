import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.deadlines import engine, service
from legalos.deadlines.models import DeadlineProposal, HolidayRow, Task
from legalos.matters.models import Matter
from legalos.matters.router import get_matter_or_404
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api", tags=["deadlines"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_MATTERS))]
TaskManager = Annotated[Principal, Depends(require(Permission.MANAGE_TASKS))]
Confirmer = Annotated[Principal, Depends(require(Permission.CONFIRM_DEADLINES))]

RuleSet = Literal["cpc", "clt", "jec"]
TriggerKind = Literal["disponibilizacao_dje", "ciencia"]
Unit = Literal["dias_uteis", "dias_corridos"]
DoublingReason = Literal[
    "fazenda_publica", "ministerio_publico", "defensoria_publica", "litisconsortes"
]
ProposalStatus = Literal["proposto", "confirmado", "rejeitado"]
TaskStatus = Literal["aberta", "concluida", "cancelada"]
HolidayKind = Literal["feriado", "ponto_facultativo", "suspensao_expediente"]


class RuleSetOut(BaseModel):
    id: RuleSet
    label: str
    basis: str


class PresetOut(BaseModel):
    id: str
    rule_set: RuleSet
    label: str
    days: int
    basis: str


class DoublingReasonOut(BaseModel):
    id: DoublingReason
    label: str


class RulesOut(BaseModel):
    rule_sets: list[RuleSetOut]
    presets: list[PresetOut]
    doubling_reasons: list[DoublingReasonOut]


class DeadlineIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    rule_set: RuleSet
    preset_id: str | None = Field(default=None, max_length=50)
    trigger_kind: TriggerKind
    trigger_date: date
    days: int = Field(ge=1, le=3650)
    unit: Unit = "dias_uteis"
    doubled_reason: DoublingReason | None = None


class StepOut(BaseModel):
    label: str
    detail: str


class PreviewOut(BaseModel):
    proposed_date: date
    steps: list[StepOut]


class ProposalOut(BaseModel):
    id: uuid.UUID
    matter_id: uuid.UUID
    title: str
    rule_set: RuleSet
    trigger_kind: TriggerKind
    trigger_date: date
    days: int
    unit: Unit
    doubled_reason: DoublingReason | None
    proposed_date: date
    steps: list[StepOut]
    status: ProposalStatus
    confirmed_date: date | None
    decision_note: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    created_at: datetime


class DecisionIn(BaseModel):
    decision: Literal["confirmado", "rejeitado"]
    confirmed_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)


class TaskOut(BaseModel):
    id: uuid.UUID
    matter_id: uuid.UUID
    matter_title: str
    title: str
    due_date: date | None
    assignee_user_id: uuid.UUID | None
    assignee_name: str | None
    status: TaskStatus
    origin: Literal["manual", "prazo"]
    notes: str | None
    created_at: datetime


class HolidayIn(BaseModel):
    day: date
    name: str = Field(min_length=2, max_length=200)
    kind: HolidayKind = "feriado"
    scope: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=300)


class HolidayOut(BaseModel):
    id: uuid.UUID | None
    day: date
    name: str
    kind: HolidayKind
    scope: str | None
    source: str | None
    system: bool


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    assert principal.tenant_id is not None
    return principal.tenant_id, principal.user_id


def _raise(e: service.DeadlineError) -> None:
    raise HTTPException(e.status_code, e.code) from e


def _input(body: DeadlineIn) -> engine.DeadlineInput:
    return engine.DeadlineInput(
        rule_set=body.rule_set,
        trigger_kind=body.trigger_kind,
        trigger_date=body.trigger_date,
        days=body.days,
        unit=body.unit,
        doubled_reason=body.doubled_reason,
    )


def _proposal_out(db: DbSession, p: DeadlineProposal) -> ProposalOut:
    decided_by = (
        db.scalar(select(User.name).where(User.id == p.decided_by)) if p.decided_by else None
    )
    return ProposalOut(
        id=p.id,
        matter_id=p.matter_id,
        title=p.title,
        rule_set=p.rule_set,
        trigger_kind=p.trigger_kind,
        trigger_date=p.trigger_date,
        days=p.days,
        unit=p.unit,
        doubled_reason=p.doubled_reason,
        proposed_date=p.proposed_date,
        steps=[StepOut(**s) for s in p.reasoning],
        status=p.status,
        confirmed_date=p.confirmed_date,
        decision_note=p.decision_note,
        decided_by_name=decided_by,
        decided_at=p.decided_at,
        created_at=p.created_at,
    )


def _task_out(db: DbSession, t: Task, matter_title: str | None = None) -> TaskOut:
    if matter_title is None:
        matter_title = db.scalar(select(Matter.title).where(Matter.id == t.matter_id)) or ""
    assignee = (
        db.scalar(select(User.name).where(User.id == t.assignee_user_id))
        if t.assignee_user_id
        else None
    )
    return TaskOut(
        id=t.id,
        matter_id=t.matter_id,
        matter_title=matter_title,
        title=t.title,
        due_date=t.due_date,
        assignee_user_id=t.assignee_user_id,
        assignee_name=assignee,
        status=t.status,
        origin=t.origin,
        notes=t.notes,
        created_at=t.created_at,
    )


@router.get("/deadline-rules")
def rules(_: Viewer) -> RulesOut:
    return RulesOut(
        rule_sets=[
            RuleSetOut(id=r.id, label=r.label, basis=r.business_days_basis)
            for r in engine.RULE_SETS.values()
        ],
        presets=[PresetOut(**p.__dict__) for p in engine.PRESETS],
        doubling_reasons=[
            DoublingReasonOut(id=k, label=v) for k, v in engine.DOUBLING_REASONS.items()
        ],
    )


@router.post("/deadline-preview")
def preview(body: DeadlineIn, _: Viewer, db: DbSession) -> PreviewOut:
    """Calculate without saving, so the user can see the reasoning before proposing."""
    try:
        result = service.compute(db, _input(body))
    except service.DeadlineError as e:
        _raise(e)
    return PreviewOut(
        proposed_date=result.proposed_date,
        steps=[StepOut(label=s.label, detail=s.detail) for s in result.steps],
    )


@router.get("/matters/{matter_id}/deadline-proposals")
def list_proposals(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> list[ProposalOut]:
    get_matter_or_404(db, matter_id)
    proposals = db.scalars(
        select(DeadlineProposal)
        .where(DeadlineProposal.matter_id == matter_id)
        .order_by(DeadlineProposal.created_at.desc())
    )
    return [_proposal_out(db, p) for p in proposals]


@router.post("/matters/{matter_id}/deadline-proposals", status_code=201)
def create_proposal(
    matter_id: uuid.UUID, body: DeadlineIn, principal: TaskManager, db: DbSession
) -> ProposalOut:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        proposal = service.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            matter=matter,
            title=body.title,
            inp=_input(body),
            preset_id=body.preset_id,
        )
    except service.DeadlineError as e:
        _raise(e)
    return _proposal_out(db, proposal)


@router.post("/deadline-proposals/{proposal_id}/decision")
def decide(
    proposal_id: uuid.UUID,
    body: DecisionIn,
    request: Request,
    principal: Confirmer,
    db: DbSession,
) -> ProposalOut:
    proposal = db.get(DeadlineProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "deadline_not_found")
    try:
        service.decide(
            db,
            user_id=principal.user_id,
            proposal=proposal,
            decision=body.decision,
            confirmed_date=body.confirmed_date,
            note=body.note,
            ip=client_ip(request),
        )
    except service.DeadlineError as e:
        _raise(e)
    return _proposal_out(db, proposal)


@router.get("/matters/{matter_id}/tasks")
def list_matter_tasks(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> list[TaskOut]:
    matter = get_matter_or_404(db, matter_id)
    tasks = db.scalars(
        select(Task)
        .where(Task.matter_id == matter_id)
        .order_by(Task.status, Task.due_date.nulls_last(), Task.created_at)
    )
    return [_task_out(db, t, matter.title) for t in tasks]


@router.post("/matters/{matter_id}/tasks", status_code=201)
def create_task(
    matter_id: uuid.UUID, body: TaskIn, principal: TaskManager, db: DbSession
) -> TaskOut:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        task = service.create_task(
            db, tenant_id=tenant_id, user_id=user_id, matter=matter, **body.model_dump()
        )
    except service.DeadlineError as e:
        _raise(e)
    return _task_out(db, task, matter.title)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: uuid.UUID, body: TaskPatch, principal: TaskManager, db: DbSession
) -> TaskOut:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task_not_found")
    try:
        service.update_task(
            db, user_id=principal.user_id, task=task, changes=body.model_dump(exclude_unset=True)
        )
    except service.DeadlineError as e:
        _raise(e)
    return _task_out(db, task)


@router.get("/tasks")
def list_tasks(
    principal: Viewer, db: DbSession, status: TaskStatus = "aberta", mine: bool = False
) -> list[TaskOut]:
    """Tasks across all processos of the firm, soonest due date first."""
    stmt = (
        select(Task, Matter.title)
        .join(Matter, Matter.id == Task.matter_id)
        .where(Task.status == status)
        .order_by(Task.due_date.nulls_last(), Task.created_at)
        .limit(500)
    )
    if mine:
        stmt = stmt.where(Task.assignee_user_id == principal.user_id)
    return [_task_out(db, t, title) for t, title in db.execute(stmt).all()]


@router.get("/holidays")
def list_holidays(
    _: Viewer, db: DbSession, year: Annotated[int, Query(ge=2000, le=2100)]
) -> list[HolidayOut]:
    rows = db.scalars(
        select(HolidayRow)
        .where(HolidayRow.day.between(date(year, 1, 1), date(year, 12, 31)))
        .order_by(HolidayRow.day)
    )
    return [
        HolidayOut(
            id=r.id,
            day=r.day,
            name=r.name,
            kind=r.kind,
            scope=r.scope,
            source=r.source,
            system=r.tenant_id is None,
        )
        for r in rows
    ]


@router.get("/holidays/suggestions")
def holiday_suggestions(
    _: Viewer, db: DbSession, year: Annotated[int, Query(ge=2000, le=2100)]
) -> list[HolidayOut]:
    """Movable dates on which courts usually close, not yet in the firm's calendar.
    They depend on each court's own calendar, so the firm must confirm before adding."""
    existing = service.holiday_map(db, date(year, 1, 1), date(year, 12, 31))
    return [
        HolidayOut(
            id=None,
            day=h.day,
            name=h.name,
            kind="ponto_facultativo",
            scope=None,
            source="Data móvel calculada; confirme no calendário do tribunal",
            system=False,
        )
        for h in engine.movable_suggestions(year)
        if h.day not in existing
    ]


@router.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, principal: Confirmer, db: DbSession) -> HolidayOut:
    tenant_id, user_id = _ids(principal)
    try:
        row = service.add_holiday(db, tenant_id=tenant_id, user_id=user_id, **body.model_dump())
    except service.DeadlineError as e:
        _raise(e)
    return HolidayOut(
        id=row.id,
        day=row.day,
        name=row.name,
        kind=row.kind,
        scope=row.scope,
        source=row.source,
        system=False,
    )


@router.delete("/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: uuid.UUID, principal: Confirmer, db: DbSession) -> None:
    row = db.get(HolidayRow, holiday_id)
    # National holidays (no firm) cannot be removed by a firm.
    if row is None or row.tenant_id is None:
        raise HTTPException(404, "holiday_not_found")
    db.delete(row)
    db.flush()
