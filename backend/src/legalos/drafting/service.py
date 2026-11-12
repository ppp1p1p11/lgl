"""Drafting: fill a template from the processo, have the AI write the fact and law
sections from cited sources, and let people edit. Drafts are AI outputs: versioned,
flagged where unsupported, and final only when a lawyer approves a version."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from legalos.ai import prompts, review
from legalos.ai.common import (
    CitationRecord,
    add_citations,
    caller,
    is_claim,
    provider_name,
    run_job,
    save_output,
)
from legalos.ai.models import AiCitation, AiOutput, AiOutputVersion, AiRun
from legalos.ai.research import source_title
from legalos.ai.verify import PageText, locate
from legalos.auth.models import User
from legalos.corpus import search as corpus_search
from legalos.documents.models import Document, DocumentChunk, DocumentPage
from legalos.drafting.templates import TEMPLATES, Section, Template
from legalos.gateway import service as gateway
from legalos.gateway.types import AIRequest, DocumentInput, TextPart
from legalos.jobs.models import Job
from legalos.jobs.queue import enqueue, handler
from legalos.matters.models import Client, Matter, MatterParty
from legalos.matters.service import add_event, reveal_document_number
from legalos.tenancy.models import Tenant

MAX_DOCUMENTS = 6
MAX_SOURCE_CHARS = 150_000
MONTHS = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


class DraftError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def start_draft(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    matter: Matter,
    template_id: str,
    instructions: str | None,
    legal_topics: str | None,
) -> AiRun:
    if template_id not in TEMPLATES:
        raise DraftError("unknown_template")
    if gateway.get_provider() is None:
        raise DraftError("ai_not_configured", 503)
    run = AiRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        matter_id=matter.id,
        workflow="drafting",
        started_by=user_id,
        input={
            "template_id": template_id,
            "instructions": (instructions or "").strip(),
            "legal_topics": (legal_topics or "").strip(),
        },
    )
    db.add(run)
    db.flush()
    enqueue(
        db,
        "ai.draft",
        tenant_id=tenant_id,
        enqueued_by=user_id,
        payload={"run_id": str(run.id)},
        max_attempts=3,
    )
    return run


@handler("ai.draft")
def draft(db: Session, job: Job) -> None:
    run_job(db, job, _draft, failure_summary="A minuta não pôde ser gerada")


def placeholder(what: str) -> str:
    return f"[PREENCHER: {what}]"


def _variables(db: Session, run: AiRun, matter: Matter) -> dict[str, str]:
    """Values for the template's {placeholders}. Missing data becomes a visible marker."""
    client = db.get(Client, matter.client_id)
    assert client is not None
    tenant = db.get(Tenant, run.tenant_id)
    author = db.get(User, run.started_by) if run.started_by else None
    number = reveal_document_number(client.kind, client.document_number_encrypted, masked=False)
    id_label = "CPF" if client.kind == "PF" else "CNPJ"
    qualification = (
        f"{client.name}, inscrito(a) no {id_label} sob o nº {number}"
        if number
        else f"{client.name}, {placeholder(f'{id_label} e qualificação')}"
    )
    others = [
        p.name
        for p in db.scalars(
            select(MatterParty)
            .where(MatterParty.matter_id == matter.id, MatterParty.is_client.is_(False))
            .order_by(MatterParty.created_at)
        )
    ]
    today = date.today()
    return {
        "vara": matter.vara or placeholder("vara"),
        "comarca": (matter.comarca or placeholder("comarca")).upper(),
        "cidade": matter.comarca or placeholder("cidade"),
        "numero_processo": matter.cnj_number or placeholder("número do processo"),
        "cliente_nome": client.name,
        "cliente_qualificacao": qualification,
        "parte_contraria": " e ".join(others) or placeholder("parte contrária"),
        "data": f"{today.day} de {MONTHS[today.month - 1]} de {today.year}",
        "advogado_nome": author.name if author else placeholder("advogado"),
        "advogado_oab": (
            f"OAB/{author.oab_uf} {author.oab_number}"
            if author and author.oab_number
            else placeholder("OAB")
        ),
        "escritorio": tenant.name if tenant else placeholder("escritório"),
    }


@dataclass
class _DocSource:
    version_id: uuid.UUID
    title: str
    chunks: list[DocumentChunk]
    pages: list[PageText]


def _matter_documents(db: Session, matter: Matter) -> list[_DocSource]:
    sources: list[_DocSource] = []
    total = 0
    documents = db.scalars(
        select(Document)
        .where(Document.matter_id == matter.id, Document.current_version_id.is_not(None))
        .order_by(Document.created_at)
        .limit(MAX_DOCUMENTS)
    )
    for document in documents:
        chunks = list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_version_id == document.current_version_id)
                .order_by(DocumentChunk.page_number, DocumentChunk.char_start)
            )
        )
        kept = []
        for chunk in chunks:
            if total + len(chunk.text) > MAX_SOURCE_CHARS:
                break
            kept.append(chunk)
            total += len(chunk.text)
        if not kept:
            continue
        pages = [
            PageText(p.page_number, p.text)
            for p in db.scalars(
                select(DocumentPage).where(
                    DocumentPage.document_version_id == document.current_version_id
                )
            )
        ]
        assert document.current_version_id is not None
        sources.append(_DocSource(document.current_version_id, document.title, kept, pages))
    return sources


class _Builder:
    """Accumulates sections; segment indexes are global so citations can point at them."""

    def __init__(self) -> None:
        self.sections: list[dict[str, Any]] = []
        self.citations: list[CitationRecord] = []
        self.count = 0

    def start(self, heading: str | None, kind: str) -> None:
        self.sections.append({"heading": heading, "kind": kind, "segments": []})

    def add(self, text: str, kind: str, *, unverified: bool = False) -> int:
        index = self.count
        self.sections[-1]["segments"].append(
            {"index": index, "text": text, "kind": kind, "unverified": unverified}
        )
        self.count += 1
        return index


def _draft(db: Session, run: AiRun) -> None:
    run.status = "running"
    assert run.matter_id is not None
    matter = db.get(Matter, run.matter_id)
    assert matter is not None
    template = TEMPLATES[run.input["template_id"]]
    variables = _variables(db, run, matter)
    call = caller(db, run)
    builder = _Builder()

    for section in template.sections:
        builder.start(section.heading, section.kind)
        if section.kind in ("fixed", "manual"):
            builder.add(section.body.format(**variables), section.kind)
        elif section.kind == "ai_facts":
            _facts_section(db, run, matter, template, section, variables, call, builder)
        else:
            _law_section(db, run, matter, template, section, variables, call, builder)

    pending = sorted(
        {
            marker
            for s in builder.sections
            for seg in s["segments"]
            for marker in _markers(seg["text"])
        }
    )
    content = {
        "template_id": template.id,
        "title": f"{template.name} — {matter.title}",
        "sections": builder.sections,
        "pending": pending,
        "provider": provider_name(),
    }
    save_output(db, run, "draft", content, builder.citations)
    run.status, run.finished_at = "succeeded", datetime.now(UTC)
    add_event(
        db,
        tenant_id=run.tenant_id,
        matter_id=matter.id,
        kind="minuta_gerada",
        summary=f"Minuta gerada para revisão: {template.name}",
        actor_user_id=None,
        payload={"ai_run_id": str(run.id)},
    )


def _markers(text: str) -> list[str]:
    out, pos = [], 0
    while (start := text.find("[PREENCHER:", pos)) >= 0:
        end = text.find("]", start)
        if end < 0:
            break
        out.append(text[start + 11 : end].strip())
        pos = end + 1
    return out


def _facts_section(
    db: Session,
    run: AiRun,
    matter: Matter,
    template: Template,
    section: Section,
    variables: dict[str, str],
    call: Any,
    builder: _Builder,
) -> None:
    sources = _matter_documents(db, matter)
    if not sources:
        builder.add(
            placeholder("fatos (não há documentos processados neste processo)"), "placeholder"
        )
        return
    response = call(
        AIRequest(
            purpose="draft_facts",
            system=prompts.DRAFT_SYSTEM,
            instruction=prompts.DRAFT_FACTS_INSTRUCTION.format(
                heading=section.heading,
                template_name=template.name,
                client_name=variables["cliente_nome"],
                instructions=run.input["instructions"],
            ),
            documents=[DocumentInput(s.title, [c.text for c in s.chunks]) for s in sources],
            effort="high",
            max_tokens=16000,
            citations=True,
        )
    )

    def verify(document_index: int, start: int, end: int, quoted: str) -> CitationRecord | None:
        if not 0 <= document_index < len(sources):
            return None
        source = sources[document_index]
        chunks = source.chunks[start : max(end, start + 1)]
        pages = {c.page_number for c in chunks}
        found = locate(quoted, [p for p in source.pages if p.page_number in pages])
        if found is None:
            return None
        return CitationRecord(
            0,
            found.text,
            "verificado",
            page_number=found.page_number,
            char_start=found.char_start,
            char_end=found.char_end,
            document_version_id=source.version_id,
        )

    _add_ai_parts(response.parts, verify, builder)


def _law_section(
    db: Session,
    run: AiRun,
    matter: Matter,
    template: Template,
    section: Section,
    variables: dict[str, str],
    call: Any,
    builder: _Builder,
) -> None:
    topics = run.input["legal_topics"]
    hits = corpus_search.search(db, topics, limit=6) if topics else []
    if not hits:
        reason = (
            "o acervo indexado não retornou dispositivos para o tema informado"
            if topics
            else "informe o tema jurídico ao gerar a minuta"
        )
        builder.add(placeholder(f"fundamentos jurídicos ({reason})"), "placeholder")
        return
    response = call(
        AIRequest(
            purpose="draft_law",
            system=prompts.DRAFT_SYSTEM,
            instruction=prompts.DRAFT_LAW_INSTRUCTION.format(
                heading=section.heading,
                template_name=template.name,
                client_name=variables["cliente_nome"],
                topics=topics,
                instructions=run.input["instructions"],
            ),
            documents=[DocumentInput(source_title(h), [h.text]) for h in hits],
            effort="high",
            max_tokens=16000,
            citations=True,
        )
    )

    def verify(document_index: int, start: int, end: int, quoted: str) -> CitationRecord | None:
        if not 0 <= document_index < len(hits):
            return None
        hit = hits[document_index]
        found = locate(quoted, [PageText(1, hit.text)])
        if found is None:
            return None
        return CitationRecord(
            0,
            found.text,
            "verificado",
            char_start=found.char_start,
            char_end=found.char_end,
            legal_unit_version_id=hit.unit_version_id,
        )

    _add_ai_parts(response.parts, verify, builder)


def _add_ai_parts(parts: list[TextPart], verify: Any, builder: _Builder) -> None:
    for part in parts:
        if not part.text.strip():
            continue
        records = [
            record
            for c in part.citations
            if (record := verify(c.document_index, c.start_block, c.end_block, c.cited_text))
        ]
        has_marker = "[PREENCHER:" in part.text
        index = builder.add(
            part.text,
            "ai",
            unverified=is_claim(part.text) and not records and not has_marker,
        )
        for record in records:
            record.item_index = index
            builder.citations.append(record)


# --- Editing ------------------------------------------------------------------------------


def edit_section(
    db: Session,
    *,
    user_id: uuid.UUID,
    output: AiOutput,
    base_version_no: int,
    section_index: int,
    text: str,
) -> AiOutputVersion:
    """Replace one section's text with the lawyer's own wording: a new version, back to
    draft. Citations of the other sections are kept; the edited section has none."""
    if output.kind != "draft":
        raise DraftError("not_a_draft")
    if base_version_no != output.current_version_no:
        raise DraftError("stale_version", 409)
    if output.status == "aprovado":
        raise DraftError("already_decided", 409)
    base = review.current_version(db, output)
    sections: list[dict[str, Any]] = [dict(s) for s in base.content["sections"]]
    if not 0 <= section_index < len(sections):
        raise DraftError("invalid_items")
    removed = {seg["index"] for seg in sections[section_index]["segments"]}
    next_index = 1 + max((seg["index"] for s in sections for seg in s["segments"]), default=-1)
    sections[section_index] = {
        **sections[section_index],
        "segments": [
            {
                "index": next_index,
                "text": text.strip(),
                "kind": "manual",
                "unverified": False,
                "edited": True,
            }
        ],
    }
    pending = sorted({m for s in sections for seg in s["segments"] for m in _markers(seg["text"])})
    version = AiOutputVersion(
        id=uuid.uuid4(),
        tenant_id=output.tenant_id,
        ai_output_id=output.id,
        version_no=base.version_no + 1,
        content={**base.content, "sections": sections, "pending": pending},
        created_by_ai=False,
        created_by=user_id,
    )
    db.add(version)
    db.flush()
    kept = [
        CitationRecord(
            c.item_index,
            c.quoted_text,
            c.verification,
            page_number=c.page_number,
            char_start=c.char_start,
            char_end=c.char_end,
            document_version_id=c.document_version_id,
            legal_unit_version_id=c.legal_unit_version_id,
        )
        for c in db.scalars(select(AiCitation).where(AiCitation.ai_output_version_id == base.id))
        if c.item_index not in removed
    ]
    add_citations(db, output.tenant_id, version.id, kept)
    output.current_version_no = version.version_no
    output.status = "rascunho"
    db.flush()
    return version
