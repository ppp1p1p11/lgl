"""Document analysis with AI: type, key facts with verified quotes, and a cited summary.

Everything produced here is a draft (status "rascunho") until a lawyer approves a
specific version (see review.py).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from legalos.ai import prompts
from legalos.ai.models import AiCitation, AiOutput, AiOutputVersion, AiRun
from legalos.ai.verify import PageText, locate
from legalos.documents.models import Document, DocumentChunk, DocumentPage, DocumentVersion
from legalos.gateway import service as gateway
from legalos.gateway.types import AIRequest, Citation, DocumentInput, TransientProviderError
from legalos.jobs.models import Job
from legalos.jobs.queue import enqueue, handler
from legalos.matters.service import add_event

logger = logging.getLogger(__name__)

# (item index, page, char start, char end, quoted text, verification)
CitationRow = tuple[int, int | None, int | None, int | None, str, str]

# Longer documents are analysed in part (first pages), and the output says so.
MAX_DOCUMENT_CHARS = 300_000
CLASSIFY_CHARS = 8_000
# Summary passages shorter than this (headings, connectives) need no citation.
MIN_CLAIM_CHARS = 25


class AnalysisError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def start_analysis(
    db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, version: DocumentVersion
) -> AiRun:
    if gateway.get_provider() is None:
        raise AnalysisError("ai_not_configured", 503)
    if version.status != "ready":
        raise AnalysisError("document_not_ready", 409)
    running = db.scalar(
        select(AiRun).where(
            AiRun.document_version_id == version.id, AiRun.status.in_(("queued", "running"))
        )
    )
    if running is not None:
        raise AnalysisError("analysis_in_progress", 409)
    document = db.get(Document, version.document_id)
    assert document is not None
    run = AiRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=document.matter_id,
        document_version_id=version.id,
        workflow="document_analysis",
        started_by=user_id,
    )
    db.add(run)
    db.flush()
    enqueue(
        db,
        "ai.analyze_document",
        tenant_id=tenant_id,
        enqueued_by=user_id,
        payload={"run_id": str(run.id)},
        max_attempts=3,
    )
    return run


@dataclass
class _Material:
    document: Document
    pages: list[PageText]
    chunks: list[DocumentChunk]
    partial: bool


def _material(db: Session, version: DocumentVersion) -> _Material:
    document = db.get(Document, version.document_id)
    assert document is not None
    pages = [
        PageText(p.page_number, p.text)
        for p in db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_version_id == version.id)
            .order_by(DocumentPage.page_number)
        )
    ]
    chunks: list[DocumentChunk] = []
    total = 0
    partial = False
    for chunk in db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version.id)
        .order_by(DocumentChunk.page_number, DocumentChunk.char_start)
    ):
        if total + len(chunk.text) > MAX_DOCUMENT_CHARS:
            partial = True
            break
        chunks.append(chunk)
        total += len(chunk.text)
    return _Material(document, pages, chunks, partial)


@handler("ai.analyze_document")
def analyze_document(db: Session, job: Job) -> None:
    run = db.get(AiRun, uuid.UUID(job.payload["run_id"]))
    if run is None or run.status not in ("queued", "running"):
        return
    try:
        with db.begin_nested():
            _analyze(db, run)
    except TransientProviderError:
        if job.attempts < job.max_attempts:
            raise  # the queue retries with backoff
        _fail(db, run, "ai_unavailable")
    except gateway.AIError as e:
        _fail(db, run, e.code)
    except Exception:
        if job.attempts < job.max_attempts:
            raise
        logger.exception("document analysis failed", extra={"ai_run_id": str(run.id)})
        _fail(db, run, "ai_error")


def _fail(db: Session, run: AiRun, code: str) -> None:
    db.refresh(run)
    run.status, run.error_code, run.finished_at = "failed", code, datetime.now(UTC)
    add_event(
        db,
        tenant_id=run.tenant_id,
        matter_id=run.matter_id,
        kind="analise_ia_falhou",
        summary="A análise por IA não pôde ser concluída",
        actor_user_id=None,
        payload={"ai_run_id": str(run.id), "error_code": code},
    )


def _analyze(db: Session, run: AiRun) -> None:
    run.status = "running"
    version = db.get(DocumentVersion, run.document_version_id)
    assert version is not None
    material = _material(db, version)
    blocks = [c.text for c in material.chunks]
    document_input = DocumentInput(material.document.title, blocks)
    call = _caller(db, run)

    # 1. Document type (a label, not a consequential output: no approval needed).
    head: list[str] = []
    for block in blocks:
        if sum(len(b) for b in head) >= CLASSIFY_CHARS:
            break
        head.append(block)
    classified = call(
        AIRequest(
            purpose="classify_document",
            system=prompts.SYSTEM,
            instruction=prompts.CLASSIFY_INSTRUCTION,
            documents=[DocumentInput(material.document.title, head)],
            effort="low",
            max_tokens=4000,
            output_schema=prompts.CLASSIFY_SCHEMA,
        )
    )
    doc_class = (classified.json or {}).get("doc_class")
    if doc_class in prompts.DOC_CLASSES and material.document.doc_class_source != "user":
        material.document.doc_class = doc_class
        material.document.doc_class_source = "ai"

    # 2. Key facts, each kept only if its quote is found word for word.
    extracted = call(
        AIRequest(
            purpose="extract_facts",
            system=prompts.SYSTEM,
            instruction=prompts.FACTS_INSTRUCTION,
            documents=[document_input],
            effort="high",
            max_tokens=16000,
            output_schema=prompts.FACTS_SCHEMA,
        )
    )
    facts: list[dict[str, Any]] = []
    fact_citations: list[CitationRow] = []
    discarded = 0
    for raw in (extracted.json or {}).get("facts", []):
        found = locate(str(raw.get("quote", "")), material.pages)
        if found is None or raw.get("type") not in prompts.FACT_TYPES:
            discarded += 1
            continue
        fact_citations.append(
            (
                len(facts),
                found.page_number,
                found.char_start,
                found.char_end,
                found.text,
                "verificado",
            )
        )
        facts.append(
            {
                "type": raw["type"],
                "value": str(raw.get("value", "")),
                "quote": found.text,
                "page_number": found.page_number,
            }
        )
    _save_output(
        db,
        run,
        version,
        "facts",
        {
            "facts": facts,
            "discarded": discarded,
            "partial": material.partial,
            "provider": _provider_name(),
        },
        fact_citations,
    )

    # 3. Summary with citations to exact passages, each one re-checked.
    summarized = call(
        AIRequest(
            purpose="summarize_document",
            system=prompts.SYSTEM,
            instruction=prompts.SUMMARY_INSTRUCTION,
            documents=[document_input],
            effort="high",
            max_tokens=16000,
            citations=True,
        )
    )
    segments, summary_citations = _segments(summarized.parts, material)
    _save_output(
        db,
        run,
        version,
        "summary",
        {"segments": segments, "partial": material.partial, "provider": _provider_name()},
        summary_citations,
    )

    run.status, run.finished_at = "succeeded", datetime.now(UTC)
    add_event(
        db,
        tenant_id=run.tenant_id,
        matter_id=run.matter_id,
        kind="analise_ia_concluida",
        summary=f"Análise por IA pronta para revisão: {material.document.title}",
        actor_user_id=None,
        payload={"ai_run_id": str(run.id)},
    )


def _caller(db: Session, run: AiRun) -> Any:
    def call(request: AIRequest) -> Any:
        return gateway.call(
            db, tenant_id=run.tenant_id, user_id=run.started_by, ai_run_id=run.id, request=request
        )

    return call


def _provider_name() -> str:
    provider = gateway.get_provider()
    return provider.name if provider else "none"


def _segments(
    parts: list[Any], material: _Material
) -> tuple[list[dict[str, Any]], list[CitationRow]]:
    """Turn the cited answer into segments. A segment that makes a claim without a
    verified citation is flagged as not verified."""
    segments: list[dict[str, Any]] = []
    citations: list[CitationRow] = []
    in_gaps = False
    for part in parts:
        text: str = part.text
        if prompts.GAPS_HEADING.lower() in text.lower():
            in_gaps = True
        verified_any = False
        for cited in part.citations:
            found = _verify_citation(cited, material)
            if found is None:
                citations.append(
                    (len(segments), None, None, None, cited.cited_text, "nao_verificado")
                )
            else:
                verified_any = True
                citations.append(
                    (
                        len(segments),
                        found.page_number,
                        found.char_start,
                        found.char_end,
                        found.text,
                        "verificado",
                    )
                )
        is_claim = sum(c.isalnum() for c in text) >= MIN_CLAIM_CHARS and not in_gaps
        segments.append(
            {
                "text": text,
                "kind": "gap" if in_gaps else "text",
                "unverified": is_claim and not verified_any,
            }
        )
    return segments, citations


def _verify_citation(cited: Citation, material: _Material) -> Any:
    """A citation must point at real blocks and its text must be in the document."""
    chunks = material.chunks[cited.start_block : max(cited.end_block, cited.start_block + 1)]
    if not chunks:
        return None
    cited_pages = {c.page_number for c in chunks}
    return locate(cited.cited_text, [p for p in material.pages if p.page_number in cited_pages])


def _save_output(
    db: Session,
    run: AiRun,
    version: DocumentVersion,
    kind: str,
    content: dict[str, Any],
    citations: list[CitationRow],
) -> AiOutput:
    output = AiOutput(
        id=uuid.uuid4(),
        tenant_id=run.tenant_id,
        matter_id=run.matter_id,
        document_version_id=version.id,
        ai_run_id=run.id,
        kind=kind,
    )
    db.add(output)
    db.flush()
    output_version = AiOutputVersion(
        id=uuid.uuid4(),
        tenant_id=run.tenant_id,
        ai_output_id=output.id,
        version_no=1,
        content=content,
        created_by_ai=True,
    )
    db.add(output_version)
    db.flush()
    for item_index, page, start, end, quoted, verification in citations:
        db.add(
            AiCitation(
                tenant_id=run.tenant_id,
                ai_output_version_id=output_version.id,
                item_index=item_index,
                document_version_id=version.id,
                page_number=page,
                char_start=start,
                char_end=end,
                quoted_text=quoted,
                verification=verification,
            )
        )
    db.flush()
    return output
