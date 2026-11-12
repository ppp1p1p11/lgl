"""Search the legal corpus.

Full-text search in Portuguese, ranked by text relevance times the weight of the source
type (brief rule 3), restricted to the versions valid on a given date (rule 4). Explicit
citations in the question ("art. 219") are looked up directly. Semantic (vector) search
is added when the embedding model is chosen (VERIFY AI-3).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from legalos.config import get_settings

# Relative weight of each source type. The values are a product decision still to be
# reviewed with a lawyer (docs/VERIFY.md SRC-11); the order follows the brief.
SOURCE_WEIGHTS: dict[str, float] = {
    "legislacao": 1.0,
    "sumula_vinculante": 0.95,
    "precedente_qualificado": 0.9,
    "sumula": 0.8,
    "decisao": 0.6,
    "doutrina": 0.4,
}

_ARTICLE_REF = re.compile(r"\bart(?:igo)?s?\.?\s*(\d{1,2}(?:\.\d{3})+|\d+)(-[A-Z])?", re.IGNORECASE)


@dataclass(frozen=True)
class Hit:
    unit_version_id: uuid.UUID
    document_id: uuid.UUID
    doc_type: str
    identifier: str
    short_name: str
    review_status: str
    label: str
    heading_path: str | None
    text: str
    status: str
    valid_from: date | None
    valid_to: date | None
    amendment_note: str | None
    source_url: str | None
    score: float


def include_demo_corpus() -> bool:
    """The unverified demo sample is never used in production."""
    return get_settings().environment != "production"


def search(db: Session, query: str, *, on_date: date | None = None, limit: int = 8) -> list[Hit]:
    on_date = on_date or date.today()
    refs = [m.group(1) + (m.group(2) or "") for m in _ARTICLE_REF.finditer(query)]
    weights = " ".join(f"WHEN '{k}' THEN {v}" for k, v in SOURCE_WEIGHTS.items())
    rows = db.execute(
        text(
            f"""
            WITH q AS (
                -- Any of the question's words may match. Ranking favours passages that
                -- cover more of the distinct words, then denser matches.
                SELECT NULLIF(replace(plainto_tsquery('portuguese', :query)::text, '&', '|'),
                              '')::tsquery AS query,
                       tsvector_to_array(to_tsvector('portuguese', :query)) AS lexemes
            )
            SELECT v.id, d.id AS document_id, d.doc_type, d.identifier, d.short_name,
                   d.review_status, u.label, u.heading_path, v.text, v.status, v.valid_from,
                   v.valid_to, v.amendment_note, COALESCE(v.source_url, d.source_url) AS url,
                   ((SELECT count(*) FROM unnest(q.lexemes) AS l
                     WHERE v.tsv @@ quote_literal(l)::tsquery)::float
                        / GREATEST(cardinality(q.lexemes), 1)
                    + 0.1 * COALESCE(ts_rank_cd(v.tsv, q.query), 0)
                    + CASE WHEN u.label = ANY(:labels) THEN 2.0
                           WHEN u.label LIKE ANY(:label_prefixes) THEN 1.0 ELSE 0 END)
                   * (CASE d.doc_type {weights} ELSE 0.5 END) AS score
            FROM legal_unit_versions v
            JOIN legal_units u ON u.id = v.legal_unit_id
            JOIN legal_documents d ON d.id = u.legal_document_id
            CROSS JOIN q
            WHERE (v.valid_from IS NULL OR v.valid_from <= :on_date)
              AND (v.valid_to IS NULL OR v.valid_to > :on_date)
              AND (:demo OR d.review_status = 'oficial')
              AND ((q.query IS NOT NULL AND v.tsv @@ q.query)
                   OR u.label = ANY(:labels) OR u.label LIKE ANY(:label_prefixes))
            ORDER BY score DESC, u.position
            LIMIT :limit
            """  # noqa: S608 - weights come from a constant, values are bound
        ),
        {
            "query": query,
            "on_date": on_date,
            "limit": limit,
            "demo": include_demo_corpus(),
            "labels": [f"art. {r}" for r in refs],
            "label_prefixes": [f"art. {r},%" for r in refs],
        },
    ).all()
    return [
        Hit(
            unit_version_id=r.id,
            document_id=r.document_id,
            doc_type=r.doc_type,
            identifier=r.identifier,
            short_name=r.short_name,
            review_status=r.review_status,
            label=r.label,
            heading_path=r.heading_path,
            text=r.text,
            status=r.status,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            amendment_note=r.amendment_note,
            source_url=r.url,
            score=float(r.score),
        )
        for r in rows
    ]
