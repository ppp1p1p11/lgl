"""Legal research: answer a question only from the indexed corpus, with every citation
checked against the indexed text (brief rules 1, 3 and 4)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from legalos.ai import prompts
from legalos.ai.common import (
    CitationRecord,
    caller,
    is_claim,
    provider_name,
    run_job,
    save_output,
)
from legalos.ai.models import AiRun
from legalos.ai.verify import PageText, locate
from legalos.corpus import search as corpus_search
from legalos.gateway import service as gateway
from legalos.gateway.types import AIRequest, DocumentInput
from legalos.jobs.models import Job
from legalos.jobs.queue import enqueue, handler
from legalos.matters.service import add_event

MAX_SOURCES = 8

DOC_TYPE_LABELS = {
    "legislacao": "Legislação",
    "sumula_vinculante": "Súmula vinculante",
    "precedente_qualificado": "Precedente qualificado",
    "sumula": "Súmula",
    "decisao": "Decisão",
    "doutrina": "Doutrina",
}
STATUS_LABELS = {"vigente": "vigente", "revogado": "revogado", "alterado": "alterado"}


class ResearchError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def start_research(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    matter_id: uuid.UUID | None,
    on_date: date | None,
) -> AiRun:
    if gateway.get_provider() is None:
        raise ResearchError("ai_not_configured", 503)
    run = AiRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter_id,
        workflow="legal_research",
        started_by=user_id,
        input={"question": question.strip(), "on_date": (on_date or date.today()).isoformat()},
    )
    db.add(run)
    db.flush()
    enqueue(
        db,
        "ai.research",
        tenant_id=tenant_id,
        enqueued_by=user_id,
        payload={"run_id": str(run.id)},
        max_attempts=3,
    )
    return run


@handler("ai.research")
def research(db: Session, job: Job) -> None:
    run_job(db, job, _research, failure_summary="A pesquisa jurídica não pôde ser concluída")


def source_title(hit: corpus_search.Hit) -> str:
    since = f", texto vigente desde {hit.valid_from.strftime('%d/%m/%Y')}" if hit.valid_from else ""
    return (
        f"{DOC_TYPE_LABELS.get(hit.doc_type, hit.doc_type)} — {hit.short_name}, "
        f"{hit.label} ({STATUS_LABELS.get(hit.status, hit.status)}{since})"
    )


def _research(db: Session, run: AiRun) -> None:
    run.status = "running"
    question: str = run.input["question"]
    on_date = date.fromisoformat(run.input["on_date"])
    hits = corpus_search.search(db, question, on_date=on_date, limit=MAX_SOURCES)

    segments: list[dict[str, Any]] = []
    citations: list[CitationRecord] = []
    if not hits:
        # Nothing indexed supports an answer: say so instead of answering from memory.
        segments = [
            {"text": "Resposta\n", "kind": "text", "unverified": False},
            {
                "text": "O acervo jurídico indexado não contém dispositivos relacionados a "
                "esta pergunta. Nenhuma resposta foi gerada sem fonte.\n",
                "kind": "gap",
                "unverified": False,
            },
        ]
    else:
        response = caller(db, run)(
            AIRequest(
                purpose="legal_research",
                system=prompts.RESEARCH_SYSTEM,
                instruction=prompts.RESEARCH_INSTRUCTION.format(question=question),
                documents=[DocumentInput(source_title(h), [h.text]) for h in hits],
                effort="high",
                max_tokens=16000,
                citations=True,
            )
        )
        in_gaps = False
        for part in response.parts:
            if prompts.GAPS_HEADING.lower() in part.text.lower():
                in_gaps = True
            verified_any = False
            for cited in part.citations:
                hit = hits[cited.document_index] if 0 <= cited.document_index < len(hits) else None
                found = locate(cited.cited_text, [PageText(1, hit.text)]) if hit else None
                if hit is None or found is None:
                    # Drop the pointer: an unverifiable citation must not look sourced.
                    continue
                verified_any = True
                citations.append(
                    CitationRecord(
                        len(segments),
                        found.text,
                        "verificado",
                        char_start=found.char_start,
                        char_end=found.char_end,
                        legal_unit_version_id=hit.unit_version_id,
                    )
                )
            segments.append(
                {
                    "text": part.text,
                    "kind": "gap" if in_gaps else "text",
                    "unverified": is_claim(part.text) and not in_gaps and not verified_any,
                }
            )

    content = {
        "question": question,
        "on_date": on_date.isoformat(),
        "segments": segments,
        "sources": [
            {
                "unit_version_id": str(h.unit_version_id),
                "doc_type": h.doc_type,
                "identifier": h.identifier,
                "short_name": h.short_name,
                "label": h.label,
                "heading_path": h.heading_path,
                "text": h.text,
                "status": h.status,
                "valid_from": h.valid_from.isoformat() if h.valid_from else None,
                "amendment_note": h.amendment_note,
                "review_status": h.review_status,
                "source_url": h.source_url,
            }
            for h in hits
        ],
        "provider": provider_name(),
    }
    save_output(db, run, "research_answer", content, citations)
    run.status, run.finished_at = "succeeded", datetime.now(UTC)
    if run.matter_id is not None:
        add_event(
            db,
            tenant_id=run.tenant_id,
            matter_id=run.matter_id,
            kind="pesquisa_concluida",
            summary=f"Pesquisa jurídica pronta: {question[:120]}",
            actor_user_id=None,
            payload={"ai_run_id": str(run.id)},
        )
