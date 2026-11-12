import re
import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from legalos.ai import review
from legalos.ai.models import AiApproval, AiOutput, AiRun
from legalos.ai.router import OutputOut, OutputStatus, _output_out
from legalos.audit.service import record
from legalos.auth.deps import DbSession, client_ip, require
from legalos.auth.models import User
from legalos.auth.service import Principal
from legalos.drafting import service
from legalos.drafting.export import render_docx
from legalos.drafting.templates import TEMPLATES
from legalos.gateway import service as gateway
from legalos.matters.router import get_matter_or_404
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api", tags=["drafting"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_AI_OUTPUTS))]
Drafter = Annotated[Principal, Depends(require(Permission.DRAFT_AI_OUTPUTS))]

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    uses_documents: bool
    uses_legal_corpus: bool


class DraftIn(BaseModel):
    template_id: str = Field(max_length=50)
    instructions: str | None = Field(default=None, max_length=4000)
    # Subject used to find legal sources in the indexed corpus (e.g. "prazo de contestação").
    legal_topics: str | None = Field(default=None, max_length=500)


class DraftSummary(BaseModel):
    run_id: uuid.UUID
    output_id: uuid.UUID | None
    template_id: str
    template_name: str
    title: str | None
    run_status: Literal["queued", "running", "succeeded", "failed"]
    error_code: str | None
    status: OutputStatus | None
    version_no: int | None
    created_at: datetime


class DraftDetail(DraftSummary):
    provider: Literal["anthropic", "demo", "none"]
    output: OutputOut | None


class SectionEditIn(BaseModel):
    base_version_no: int
    text: str = Field(min_length=1, max_length=50000)


def _ids(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    assert principal.tenant_id is not None
    return principal.tenant_id, principal.user_id


def _summary(db: DbSession, run: AiRun) -> DraftSummary:
    output = db.scalar(select(AiOutput).where(AiOutput.ai_run_id == run.id))
    template = TEMPLATES.get(run.input.get("template_id", ""))
    title = None
    if output is not None:
        title = review.current_version(db, output).content.get("title")
    return DraftSummary(
        run_id=run.id,
        output_id=output.id if output else None,
        template_id=run.input.get("template_id", ""),
        template_name=template.name if template else "",
        title=title,
        run_status=run.status,
        error_code=run.error_code,
        status=output.status if output else None,
        version_no=output.current_version_no if output else None,
        created_at=run.created_at,
    )


def _draft_run_or_404(db: DbSession, run_id: uuid.UUID) -> AiRun:
    run = db.get(AiRun, run_id)
    if run is None or run.workflow != "drafting":
        raise HTTPException(404, "draft_not_found")
    return run


def _draft_output_or_404(db: DbSession, output_id: uuid.UUID) -> AiOutput:
    output = db.get(AiOutput, output_id)
    if output is None or output.kind != "draft":
        raise HTTPException(404, "draft_not_found")
    return output


@router.get("/draft-templates")
def list_templates(_: Viewer) -> list[TemplateOut]:
    return [
        TemplateOut(
            id=t.id,
            name=t.name,
            description=t.description,
            uses_documents=any(s.kind == "ai_facts" for s in t.sections),
            uses_legal_corpus=any(s.kind == "ai_law" for s in t.sections),
        )
        for t in TEMPLATES.values()
    ]


@router.post("/matters/{matter_id}/drafts", status_code=202)
def start_draft(
    matter_id: uuid.UUID, body: DraftIn, principal: Drafter, db: DbSession
) -> DraftSummary:
    tenant_id, user_id = _ids(principal)
    matter = get_matter_or_404(db, matter_id)
    try:
        run = service.start_draft(
            db, tenant_id=tenant_id, user_id=user_id, matter=matter, **body.model_dump()
        )
    except service.DraftError as e:
        raise HTTPException(e.status_code, e.code) from e
    return _summary(db, run)


@router.get("/matters/{matter_id}/drafts")
def list_drafts(matter_id: uuid.UUID, _: Viewer, db: DbSession) -> list[DraftSummary]:
    get_matter_or_404(db, matter_id)
    runs = db.scalars(
        select(AiRun)
        .where(AiRun.matter_id == matter_id, AiRun.workflow == "drafting")
        .order_by(AiRun.created_at.desc())
    )
    return [_summary(db, run) for run in runs]


@router.get("/drafts/{run_id}")
def get_draft(run_id: uuid.UUID, _: Viewer, db: DbSession) -> DraftDetail:
    run = _draft_run_or_404(db, run_id)
    output = db.scalar(select(AiOutput).where(AiOutput.ai_run_id == run.id))
    provider = gateway.get_provider()
    return DraftDetail(
        **_summary(db, run).model_dump(),
        provider=provider.name if provider else "none",
        output=_output_out(db, output) if output else None,
    )


@router.post("/ai-outputs/{output_id}/sections/{section_index}", status_code=201)
def edit_section(
    output_id: uuid.UUID,
    section_index: int,
    body: SectionEditIn,
    principal: Drafter,
    db: DbSession,
) -> OutputOut:
    output = _draft_output_or_404(db, output_id)
    try:
        service.edit_section(
            db,
            user_id=principal.user_id,
            output=output,
            base_version_no=body.base_version_no,
            section_index=section_index,
            text=body.text,
        )
    except service.DraftError as e:
        raise HTTPException(e.status_code, e.code) from e
    return _output_out(db, output)


def _filename(title: str, version_no: int) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()[:60] or "minuta"
    return f"{slug}-v{version_no}.docx"


@router.get("/ai-outputs/{output_id}/export.docx")
def export_docx(
    output_id: uuid.UUID, request: Request, principal: Viewer, db: DbSession
) -> Response:
    tenant_id, user_id = _ids(principal)
    output = _draft_output_or_404(db, output_id)
    version = review.current_version(db, output)
    approval_line = None
    if output.status == "aprovado":
        row = db.execute(
            select(AiApproval, User)
            .join(User, User.id == AiApproval.approver_user_id)
            .where(AiApproval.ai_output_version_id == version.id, AiApproval.decision == "aprovado")
        ).first()
        if row:
            approval, user = row
            oab = f" (OAB/{user.oab_uf} {user.oab_number})" if user.oab_number else ""
            approval_line = (
                f"Aprovado por {user.name}{oab} em "
                f"{approval.decided_at.strftime('%d/%m/%Y')} — versão {version.version_no}."
            )
    data = render_docx(
        version.content,
        status=output.status,
        version_no=version.version_no,
        approval_line=approval_line,
    )
    record(
        db,
        "draft.exported",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        entity_type="ai_output_version",
        entity_id=str(version.id),
        ip=client_ip(request),
        details={"status": output.status},
    )
    filename = _filename(version.content.get("title", "minuta"), version.version_no)
    return Response(
        content=data,
        media_type=DOCX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
