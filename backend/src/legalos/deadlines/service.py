"""Deadline proposals, their confirmation by a lawyer, tasks and holiday calendars."""

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from legalos.audit.service import record
from legalos.deadlines import engine
from legalos.deadlines.models import DeadlineProposal, HolidayRow, Task
from legalos.matters.models import Matter
from legalos.matters.service import add_event


class DeadlineError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def holiday_map(db: Session, start: date, end: date) -> dict[date, str]:
    """Days without court business visible to the current firm (national + its own)."""
    rows = db.execute(
        select(HolidayRow.day, HolidayRow.name).where(HolidayRow.day.between(start, end))
    ).all()
    return {r.day: r.name for r in rows}


def compute(db: Session, inp: engine.DeadlineInput) -> engine.DeadlineResult:
    # Generous window: doubled business-day deadlines, recess and weekends included.
    horizon = inp.trigger_date + timedelta(days=inp.days * 4 + 120)
    try:
        return engine.calculate(inp, holiday_map(db, inp.trigger_date, horizon))
    except ValueError as e:
        raise DeadlineError("invalid_deadline_input") from e


def create_proposal(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter: Matter,
    title: str,
    inp: engine.DeadlineInput,
    preset_id: str | None,
) -> DeadlineProposal:
    result = compute(db, inp)
    proposal = DeadlineProposal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter.id,
        title=title.strip(),
        rule_set=inp.rule_set,
        preset_id=preset_id,
        trigger_kind=inp.trigger_kind,
        trigger_date=inp.trigger_date,
        days=inp.days,
        unit=inp.unit,
        doubled_reason=inp.doubled_reason,
        proposed_date=result.proposed_date,
        reasoning=[asdict(s) for s in result.steps],
        created_by=user_id,
    )
    db.add(proposal)
    db.flush()
    add_event(
        db,
        tenant_id=tenant_id,
        matter_id=matter.id,
        kind="prazo_proposto",
        summary=f"Prazo proposto: {proposal.title} — "
        f"{result.proposed_date.strftime('%d/%m/%Y')} (aguarda confirmação)",
        actor_user_id=user_id,
        source="manual",
        payload={"deadline_proposal_id": str(proposal.id)},
    )
    return proposal


def decide(
    db: Session,
    *,
    user_id: uuid.UUID,
    proposal: DeadlineProposal,
    decision: str,
    confirmed_date: date | None,
    note: str | None,
    ip: str | None,
) -> DeadlineProposal:
    """A lawyer confirms (optionally with a different date and a note) or rejects."""
    if proposal.status != "proposto":
        raise DeadlineError("already_decided", 409)
    if decision == "confirmado":
        final = confirmed_date or proposal.proposed_date
        if final != proposal.proposed_date and not (note or "").strip():
            raise DeadlineError("note_required_for_different_date")
        proposal.confirmed_date = final
    proposal.status = decision
    proposal.decision_note = (note or "").strip() or None
    proposal.decided_by = user_id
    proposal.decided_at = datetime.now(UTC)
    db.flush()
    if decision == "confirmado":
        assert proposal.confirmed_date is not None
        db.add(
            Task(
                tenant_id=proposal.tenant_id,
                matter_id=proposal.matter_id,
                title=f"Prazo: {proposal.title}",
                due_date=proposal.confirmed_date,
                origin="prazo",
                deadline_proposal_id=proposal.id,
                created_by=user_id,
            )
        )
        summary = (
            f"Prazo confirmado: {proposal.title} — {proposal.confirmed_date.strftime('%d/%m/%Y')}"
        )
    else:
        summary = f"Proposta de prazo rejeitada: {proposal.title}"
    add_event(
        db,
        tenant_id=proposal.tenant_id,
        matter_id=proposal.matter_id,
        kind=f"prazo_{decision}",
        summary=summary,
        actor_user_id=user_id,
        source="manual",
        payload={"deadline_proposal_id": str(proposal.id)},
    )
    record(
        db,
        f"deadline.{decision}",
        tenant_id=proposal.tenant_id,
        actor_user_id=user_id,
        entity_type="deadline_proposal",
        entity_id=str(proposal.id),
        ip=ip,
    )
    return proposal


def create_task(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter: Matter,
    title: str,
    due_date: date | None,
    assignee_user_id: uuid.UUID | None,
    notes: str | None,
) -> Task:
    task = Task(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter.id,
        title=title.strip(),
        due_date=due_date,
        assignee_user_id=assignee_user_id,
        notes=notes,
        created_by=user_id,
    )
    db.add(task)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise DeadlineError("not_a_firm_member") from e
    add_event(
        db,
        tenant_id=tenant_id,
        matter_id=matter.id,
        kind="tarefa_criada",
        summary=f"Tarefa criada: {task.title}",
        actor_user_id=user_id,
        source="manual",
    )
    return task


def update_task(db: Session, *, user_id: uuid.UUID, task: Task, changes: dict[str, object]) -> Task:
    old_status = task.status
    for name, value in changes.items():
        setattr(task, name, value)
    if task.status != old_status:
        task.completed_at = datetime.now(UTC) if task.status == "concluida" else None
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise DeadlineError("not_a_firm_member") from e
    if task.status != old_status:
        labels = {"concluida": "concluída", "cancelada": "cancelada", "aberta": "reaberta"}
        add_event(
            db,
            tenant_id=task.tenant_id,
            matter_id=task.matter_id,
            kind=f"tarefa_{task.status}",
            summary=f"Tarefa {labels[task.status]}: {task.title}",
            actor_user_id=user_id,
            source="manual",
        )
    return task


def add_holiday(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    day: date,
    name: str,
    kind: str,
    scope: str | None,
    source: str | None,
) -> HolidayRow:
    row = HolidayRow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        day=day,
        name=name.strip(),
        kind=kind,
        scope=scope,
        source=source,
        created_by=user_id,
    )
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise DeadlineError("holiday_already_exists", 409) from e
    record(
        db,
        "holiday.added",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="holiday",
        entity_id=str(row.id),
        details={"day": day.isoformat()},
    )
    return row
