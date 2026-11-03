import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from legalos.ai import review, workflows
from legalos.ai.models import AiApproval, AiCitation, AiOutput, AiOutputVersion, AiRun
from legalos.audit.service import record
from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.documents.models import Document, DocumentVersion
from legalos.gateway import service as gateway
from legalos.gateway.models import GatewayCall
from legalos.tenancy.models import Tenant
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api", tags=["ai"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_AI_OUTPUTS))]
Drafter = Annotated[Principal, Depends(require(Permission.DRAFT_AI_OUTPUTS))]
Approver = Annotated[Principal, Depends(require(Permission.APPROVE_AI_OUTPUTS))]
FirmManager = Annotated[Principal, Depends(require(Permission.MANAGE_FIRM))]

OutputStatus = Literal["rascunho", "em_revisao", "aprovado", "rejeitado"]


class RunOut(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class CitationOut(BaseModel):
    item_index: int
    page_number: int | None
    char_start: int | None
    char_end: int | None
    quoted_text: str
    verification: Literal["verificado", "nao_verificado"]


class ApprovalOut(BaseModel):
    version_no: int
    decision: Literal["aprovado", "rejeitado"]
    approver_name: str
    approver_oab: str | None
    comment: str | None
    decided_at: datetime


class OutputOut(BaseModel):
    id: uuid.UUID
    kind: Literal["facts", "summary"]
    status: OutputStatus
    version_no: int
    created_by_ai: bool
    note: str | None
    content: dict[str, Any]
    citations: list[CitationOut]
    approvals: list[ApprovalOut]


class AnalysisOut(BaseModel):
    provider: Literal["anthropic", "demo", "none"]
    doc_class: str | None
    doc_class_source: Literal["ai", "user"] | None
    run: RunOut | None
    outputs: list[OutputOut]


class VersionRef(BaseModel):
    version_no: int


class DecisionIn(VersionRef):
    decision: Literal["aprovado", "rejeitado"]
    comment: str | None = Field(default=None, max_length=2000)


class RemoveItemsIn(BaseModel):
    base_version_no: int
    remove: list[int] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class AiUsageOut(BaseModel):
    month_spend_usd: Decimal
    monthly_budget_usd: Decimal
    redaction_enabled: bool
    calls_this_month: int


class AiSettingsIn(BaseModel):
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0, le=100000)
    redaction_enabled: bool | None = None


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    assert principal.tenant_id is not None
    return principal.tenant_id, principal.user_id


def _version_or_404(db: DbSession, version_id: uuid.UUID) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "document_not_found")
    return version


def _output_or_404(db: DbSession, output_id: uuid.UUID) -> AiOutput:
    output = db.get(AiOutput, output_id)
    if output is None:
        raise HTTPException(404, "ai_output_not_found")
    return output


def _output_out(db: DbSession, output: AiOutput) -> OutputOut:
    version = review.current_version(db, output)
    citations = db.scalars(
        select(AiCitation)
        .where(AiCitation.ai_output_version_id == version.id)
        .order_by(AiCitation.item_index)
    )
    approvals = db.execute(
        select(AiApproval, User)
        .join(User, User.id == AiApproval.approver_user_id)
        .join(AiOutputVersion, AiOutputVersion.id == AiApproval.ai_output_version_id)
        .where(AiOutputVersion.ai_output_id == output.id)
        .order_by(AiApproval.decided_at.desc())
    ).all()
    version_nos = {
        v.id: v.version_no
        for v in db.scalars(
            select(AiOutputVersion).where(AiOutputVersion.ai_output_id == output.id)
        )
    }
    return OutputOut(
        id=output.id,
        kind=output.kind,
        status=output.status,
        version_no=version.version_no,
        created_by_ai=version.created_by_ai,
        note=version.note,
        content=version.content,
        citations=[
            CitationOut(
                item_index=c.item_index,
                page_number=c.page_number,
                char_start=c.char_start,
                char_end=c.char_end,
                quoted_text=c.quoted_text,
                verification=c.verification,
            )
            for c in citations
        ],
        approvals=[
            ApprovalOut(
                version_no=version_nos[a.ai_output_version_id],
                decision=a.decision,
                approver_name=u.name,
                approver_oab=f"OAB/{u.oab_uf} {u.oab_number}" if u.oab_number else None,
                comment=a.comment,
                decided_at=a.decided_at,
            )
            for a, u in approvals
        ],
    )


@router.get("/document-versions/{version_id}/analysis")
def get_analysis(version_id: uuid.UUID, _: Viewer, db: DbSession) -> AnalysisOut:
    version = _version_or_404(db, version_id)
    document = db.get(Document, version.document_id)
    assert document is not None
    run = db.scalar(
        select(AiRun)
        .where(AiRun.document_version_id == version.id)
        .order_by(AiRun.created_at.desc())
        .limit(1)
    )
    outputs = (
        list(
            db.scalars(select(AiOutput).where(AiOutput.ai_run_id == run.id).order_by(AiOutput.kind))
        )
        if run
        else []
    )
    provider = gateway.get_provider()
    return AnalysisOut(
        provider=provider.name if provider else "none",
        doc_class=document.doc_class,
        doc_class_source=document.doc_class_source,
        run=RunOut(
            id=run.id,
            status=run.status,
            error_code=run.error_code,
            created_at=run.created_at,
            finished_at=run.finished_at,
        )
        if run
        else None,
        outputs=[_output_out(db, o) for o in outputs],
    )


@router.post("/document-versions/{version_id}/analysis", status_code=202)
def start_analysis(version_id: uuid.UUID, principal: Drafter, db: DbSession) -> RunOut:
    tenant_id, user_id = _ids(principal)
    version = _version_or_404(db, version_id)
    try:
        run = workflows.start_analysis(db, tenant_id=tenant_id, user_id=user_id, version=version)
    except workflows.AnalysisError as e:
        raise HTTPException(e.status_code, e.code) from e
    return RunOut(
        id=run.id, status="queued", error_code=None, created_at=run.created_at, finished_at=None
    )


@router.post("/ai-outputs/{output_id}/submit")
def submit(output_id: uuid.UUID, body: VersionRef, principal: Drafter, db: DbSession) -> OutputOut:
    output = _output_or_404(db, output_id)
    try:
        review.submit_for_review(
            db, user_id=principal.user_id, output=output, version_no=body.version_no
        )
    except review.ReviewError as e:
        raise HTTPException(e.status_code, e.code) from e
    return _output_out(db, output)


@router.post("/ai-outputs/{output_id}/decision")
def decide(
    output_id: uuid.UUID, body: DecisionIn, request: Request, principal: Approver, db: DbSession
) -> OutputOut:
    output = _output_or_404(db, output_id)
    try:
        review.decide(
            db,
            user_id=principal.user_id,
            output=output,
            version_no=body.version_no,
            decision=body.decision,
            comment=body.comment,
            ip=client_ip(request),
        )
    except review.ReviewError as e:
        raise HTTPException(e.status_code, e.code) from e
    return _output_out(db, output)


@router.post("/ai-outputs/{output_id}/versions", status_code=201)
def remove_items(
    output_id: uuid.UUID, body: RemoveItemsIn, principal: Drafter, db: DbSession
) -> OutputOut:
    output = _output_or_404(db, output_id)
    try:
        review.remove_items(
            db,
            user_id=principal.user_id,
            output=output,
            base_version_no=body.base_version_no,
            remove=body.remove,
            note=body.note,
        )
    except review.ReviewError as e:
        raise HTTPException(e.status_code, e.code) from e
    return _output_out(db, output)


@router.get("/firm/ai-usage")
def ai_usage(principal: Viewer, db: DbSession) -> AiUsageOut:
    tenant_id, _user = _ids(principal)
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    month_start = func.date_trunc("month", func.now())
    calls = (
        db.scalar(
            select(func.count())
            .select_from(GatewayCall)
            .where(GatewayCall.created_at >= month_start)
        )
        or 0
    )
    return AiUsageOut(
        month_spend_usd=gateway.month_spend(db, tenant_id),
        monthly_budget_usd=tenant.ai_monthly_budget_usd,
        redaction_enabled=tenant.ai_redaction_enabled,
        calls_this_month=calls,
    )


@router.patch("/firm/ai-settings")
def update_ai_settings(
    body: AiSettingsIn, request: Request, principal: FirmManager, db: DbSession
) -> AiUsageOut:
    tenant_id, user_id = _ids(principal)
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    if body.monthly_budget_usd is not None:
        tenant.ai_monthly_budget_usd = body.monthly_budget_usd
    if body.redaction_enabled is not None:
        tenant.ai_redaction_enabled = body.redaction_enabled
    db.flush()
    record(
        db,
        "firm.ai_settings_changed",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        ip=client_ip(request),
        details=body.model_dump(mode="json", exclude_none=True),
    )
    return ai_usage(principal, db)
