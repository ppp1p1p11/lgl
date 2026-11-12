import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from legalos.auth.deps import DbSession, require
from legalos.auth.service import Principal
from legalos.corpus import search
from legalos.corpus.models import LegalDocument, LegalUnit
from legalos.tenancy.roles import Permission

router = APIRouter(prefix="/api/corpus", tags=["corpus"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_AI_OUTPUTS))]

DocType = Literal[
    "legislacao", "sumula_vinculante", "precedente_qualificado", "sumula", "decisao", "doutrina"
]
ReviewStatus = Literal["oficial", "demonstracao_nao_conferida"]


class CorpusDocumentOut(BaseModel):
    id: uuid.UUID
    doc_type: DocType
    identifier: str
    short_name: str
    title: str
    review_status: ReviewStatus
    source_url: str | None
    units: int


class CorpusHitOut(BaseModel):
    unit_version_id: uuid.UUID
    doc_type: DocType
    identifier: str
    short_name: str
    review_status: ReviewStatus
    label: str
    heading_path: str | None
    text: str
    status: Literal["vigente", "revogado", "alterado"]
    valid_from: date | None
    amendment_note: str | None
    source_url: str | None


@router.get("/documents")
def list_documents(_: Viewer, db: DbSession) -> list[CorpusDocumentOut]:
    """What is indexed. Research can only cite what appears here."""
    stmt = (
        select(LegalDocument, func.count(LegalUnit.id))
        .outerjoin(LegalUnit, LegalUnit.legal_document_id == LegalDocument.id)
        .group_by(LegalDocument.id)
        .order_by(LegalDocument.short_name)
    )
    if not search.include_demo_corpus():
        stmt = stmt.where(LegalDocument.review_status == "oficial")
    return [
        CorpusDocumentOut(
            id=d.id,
            doc_type=d.doc_type,
            identifier=d.identifier,
            short_name=d.short_name,
            title=d.title,
            review_status=d.review_status,
            source_url=d.source_url,
            units=count,
        )
        for d, count in db.execute(stmt).all()
    ]


@router.get("/search")
def search_corpus(
    _: Viewer,
    db: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    on_date: date | None = None,
) -> list[CorpusHitOut]:
    """Direct search of the indexed texts (no AI)."""
    return [
        CorpusHitOut(
            unit_version_id=h.unit_version_id,
            doc_type=h.doc_type,
            identifier=h.identifier,
            short_name=h.short_name,
            review_status=h.review_status,
            label=h.label,
            heading_path=h.heading_path,
            text=h.text,
            status=h.status,
            valid_from=h.valid_from,
            amendment_note=h.amendment_note,
            source_url=h.source_url,
        )
        for h in search.search(db, q, on_date=on_date, limit=20)
    ]
