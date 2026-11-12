"""Pieces shared by every AI workflow: running the job safely, saving versioned outputs
with their citations, and recording failures."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from legalos.ai.models import AiCitation, AiOutput, AiOutputVersion, AiRun
from legalos.gateway import service as gateway
from legalos.gateway.types import AIRequest, AIResponse, TransientProviderError
from legalos.jobs.models import Job
from legalos.matters.service import add_event

logger = logging.getLogger(__name__)

# Passages shorter than this (headings, connectives) need no citation.
MIN_CLAIM_CHARS = 25


@dataclass
class CitationRecord:
    """Where one item of an AI output comes from: a firm document or the legal corpus."""

    item_index: int
    quoted_text: str
    verification: str  # "verificado" | "nao_verificado"
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    document_version_id: uuid.UUID | None = None
    legal_unit_version_id: uuid.UUID | None = None


def run_job(
    db: Session, job: Job, work: Callable[[Session, AiRun], None], *, failure_summary: str
) -> None:
    """Run one AI workflow. Transient provider errors are retried by the queue; anything
    else ends the run with a reason the user can see."""
    run = db.get(AiRun, uuid.UUID(job.payload["run_id"]))
    if run is None or run.status not in ("queued", "running"):
        return
    try:
        with db.begin_nested():
            work(db, run)
    except TransientProviderError:
        if job.attempts < job.max_attempts:
            raise
        fail(db, run, "ai_unavailable", failure_summary)
    except gateway.AIError as e:
        fail(db, run, e.code, failure_summary)
    except Exception:
        if job.attempts < job.max_attempts:
            raise
        logger.exception("ai workflow failed", extra={"ai_run_id": str(run.id)})
        fail(db, run, "ai_error", failure_summary)


def fail(db: Session, run: AiRun, code: str, summary: str) -> None:
    db.refresh(run)
    run.status, run.error_code, run.finished_at = "failed", code, datetime.now(UTC)
    if run.matter_id is not None:
        add_event(
            db,
            tenant_id=run.tenant_id,
            matter_id=run.matter_id,
            kind="ia_falhou",
            summary=summary,
            actor_user_id=None,
            payload={"ai_run_id": str(run.id), "error_code": code},
        )


def caller(db: Session, run: AiRun) -> Callable[[AIRequest], AIResponse]:
    def call(request: AIRequest) -> AIResponse:
        return gateway.call(
            db, tenant_id=run.tenant_id, user_id=run.started_by, ai_run_id=run.id, request=request
        )

    return call


def provider_name() -> str:
    provider = gateway.get_provider()
    return provider.name if provider else "none"


def save_output(
    db: Session,
    run: AiRun,
    kind: str,
    content: dict[str, Any],
    citations: list[CitationRecord],
    *,
    document_version_id: uuid.UUID | None = None,
) -> AiOutput:
    output = AiOutput(
        id=uuid.uuid4(),
        tenant_id=run.tenant_id,
        matter_id=run.matter_id,
        document_version_id=document_version_id,
        ai_run_id=run.id,
        kind=kind,
    )
    db.add(output)
    db.flush()
    version = AiOutputVersion(
        id=uuid.uuid4(),
        tenant_id=run.tenant_id,
        ai_output_id=output.id,
        version_no=1,
        content=content,
        created_by_ai=True,
    )
    db.add(version)
    db.flush()
    add_citations(db, run.tenant_id, version.id, citations)
    return output


def add_citations(
    db: Session,
    tenant_id: uuid.UUID,
    output_version_id: uuid.UUID,
    citations: list[CitationRecord],
) -> None:
    for c in citations:
        db.add(
            AiCitation(
                tenant_id=tenant_id,
                ai_output_version_id=output_version_id,
                item_index=c.item_index,
                document_version_id=c.document_version_id,
                legal_unit_version_id=c.legal_unit_version_id,
                page_number=c.page_number,
                char_start=c.char_start,
                char_end=c.char_end,
                quoted_text=c.quoted_text,
                verification=c.verification,
            )
        )
    db.flush()


def is_claim(text: str) -> bool:
    return sum(ch.isalnum() for ch in text) >= MIN_CLAIM_CHARS
