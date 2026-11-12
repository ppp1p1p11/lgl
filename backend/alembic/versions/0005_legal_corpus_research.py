"""Legal corpus (global, read-only to firms) and research/drafting AI outputs.

The corpus is shared by every firm and contains only public legal texts, so it has no
tenant column. The app role can only read it; ingestion runs as the owner role.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


SCHEMA = """
CREATE TABLE corpus_ingestion_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source varchar(300) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed')),
    stats jsonb NOT NULL DEFAULT '{}',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE legal_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Source hierarchy (brief rule 3): these types are never interchangeable.
    doc_type varchar(30) NOT NULL CHECK (doc_type IN (
        'legislacao', 'sumula_vinculante', 'precedente_qualificado', 'sumula', 'decisao',
        'doutrina')),
    identifier varchar(200) NOT NULL UNIQUE,
    short_name varchar(60) NOT NULL,
    title varchar(500) NOT NULL,
    issuing_body varchar(200),
    urn varchar(300),
    publication_date date,
    source_url varchar(1000),
    -- 'oficial': text retrieved from an official source, with provenance.
    -- 'demonstracao_nao_conferida': sample text for demos, NOT checked against the
    -- official source; never used in production.
    review_status varchar(40) NOT NULL DEFAULT 'oficial'
        CHECK (review_status IN ('oficial', 'demonstracao_nao_conferida')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE legal_units (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_document_id uuid NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
    parent_id uuid REFERENCES legal_units(id) ON DELETE CASCADE,
    unit_type varchar(30) NOT NULL,
    -- Human citation, e.g. "art. 224, § 1º" or "Súmula 7".
    label varchar(200) NOT NULL,
    -- Section headings above the unit, e.g. "Livro IV > Título I > Capítulo III".
    heading_path varchar(1000),
    position integer NOT NULL,
    UNIQUE (legal_document_id, label)
);

CREATE TABLE legal_unit_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_unit_id uuid NOT NULL REFERENCES legal_units(id) ON DELETE CASCADE,
    text text NOT NULL,
    -- Temporal validity (brief rule 4). NULL valid_from = since the original publication.
    valid_from date,
    valid_to date,
    status varchar(20) NOT NULL DEFAULT 'vigente'
        CHECK (status IN ('vigente', 'revogado', 'alterado')),
    amendment_note varchar(500),
    content_hash char(64) NOT NULL,
    source_url varchar(1000),
    retrieved_at timestamptz,
    ingestion_run_id uuid REFERENCES corpus_ingestion_runs(id),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', text)) STORED,
    -- Filled when the embedding model is chosen (VERIFY AI-3).
    embedding vector,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX legal_unit_versions_unit_idx ON legal_unit_versions (legal_unit_id);
CREATE INDEX legal_unit_versions_tsv_idx ON legal_unit_versions USING gin (tsv);

-- AI runs and outputs are no longer only about one document.
ALTER TABLE ai_runs
    ALTER COLUMN matter_id DROP NOT NULL,
    ALTER COLUMN document_version_id DROP NOT NULL,
    ADD COLUMN input jsonb NOT NULL DEFAULT '{}',
    DROP CONSTRAINT ai_runs_workflow_check,
    ADD CONSTRAINT ai_runs_workflow_check
        CHECK (workflow IN ('document_analysis', 'legal_research', 'drafting'));

ALTER TABLE ai_outputs
    ALTER COLUMN matter_id DROP NOT NULL,
    ALTER COLUMN document_version_id DROP NOT NULL,
    DROP CONSTRAINT ai_outputs_kind_check,
    ADD CONSTRAINT ai_outputs_kind_check
        CHECK (kind IN ('facts', 'summary', 'research_answer', 'draft'));

ALTER TABLE ai_citations
    ALTER COLUMN document_version_id DROP NOT NULL,
    ADD COLUMN legal_unit_version_id uuid REFERENCES legal_unit_versions(id),
    ADD CONSTRAINT ai_citations_one_target CHECK (
        (document_version_id IS NOT NULL) <> (legal_unit_version_id IS NOT NULL));
"""

GRANTS = """
GRANT SELECT ON corpus_ingestion_runs, legal_documents, legal_units, legal_unit_versions
    TO {app};
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(GRANTS.format(app=_app_role()))


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM ai_citations WHERE legal_unit_version_id IS NOT NULL;
        ALTER TABLE ai_citations
            DROP CONSTRAINT ai_citations_one_target,
            DROP COLUMN legal_unit_version_id,
            ALTER COLUMN document_version_id SET NOT NULL;
        DELETE FROM ai_outputs WHERE kind IN ('research_answer', 'draft');
        ALTER TABLE ai_outputs
            DROP CONSTRAINT ai_outputs_kind_check,
            ADD CONSTRAINT ai_outputs_kind_check CHECK (kind IN ('facts', 'summary'));
        DELETE FROM ai_runs WHERE workflow <> 'document_analysis';
        ALTER TABLE ai_runs
            DROP CONSTRAINT ai_runs_workflow_check,
            ADD CONSTRAINT ai_runs_workflow_check CHECK (workflow IN ('document_analysis')),
            DROP COLUMN input;
        DROP TABLE IF EXISTS legal_unit_versions, legal_units, legal_documents,
            corpus_ingestion_runs;
        """
    )
