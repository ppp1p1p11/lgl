"""Matters and documents: clients, processos, timeline, files, pages, text search.

Adds clients, matters, parties, team, timeline, documents, versions, pages, and
Portuguese full-text search on document chunks.

Every table is firm-scoped with RLS (ADR-0002). Foreign keys between firm tables are
composite (tenant_id, id), so the database itself refuses to link a row of one firm to a
row of another, even through the owner role.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


SCHEMA = """
CREATE TABLE clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    kind char(2) NOT NULL CHECK (kind IN ('PF', 'PJ')),
    name varchar(300) NOT NULL,
    -- CPF/CNPJ: encrypted, plus a keyed hash so duplicates can be found without decrypting.
    document_number_encrypted bytea,
    document_number_hash varchar(64),
    email varchar(320),
    phone varchar(40),
    notes text,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id)
);
CREATE UNIQUE INDEX clients_document_unique
    ON clients (tenant_id, document_number_hash) WHERE document_number_hash IS NOT NULL;
CREATE INDEX clients_tenant_name_idx ON clients (tenant_id, name);

CREATE TABLE matters (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    client_id uuid NOT NULL,
    title varchar(300) NOT NULL,
    -- Null for pre-litigation matters.
    cnj_number varchar(25),
    area varchar(30) NOT NULL CHECK (area IN (
        'trabalhista', 'civel', 'tributario', 'consumidor', 'familia', 'previdenciario',
        'empresarial', 'outro')),
    court varchar(50),
    comarca varchar(120),
    vara varchar(200),
    status varchar(20) NOT NULL DEFAULT 'ativo'
        CHECK (status IN ('ativo', 'suspenso', 'encerrado', 'arquivado')),
    description text,
    opened_at date,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients (tenant_id, id)
);
CREATE UNIQUE INDEX matters_cnj_unique
    ON matters (tenant_id, cnj_number) WHERE cnj_number IS NOT NULL;
CREATE INDEX matters_client_idx ON matters (tenant_id, client_id);

CREATE TABLE matter_parties (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    name varchar(300) NOT NULL,
    kind char(2) CHECK (kind IN ('PF', 'PJ')),
    role varchar(30) NOT NULL CHECK (role IN (
        'autor', 'reu', 'reclamante', 'reclamada', 'exequente', 'executado',
        'terceiro', 'outro')),
    is_client boolean NOT NULL DEFAULT false,
    document_number_encrypted bytea,
    document_number_hash varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX matter_parties_matter_idx ON matter_parties (matter_id);

CREATE TABLE matter_members (
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    user_id uuid NOT NULL,
    responsibility varchar(20) NOT NULL DEFAULT 'equipe'
        CHECK (responsibility IN ('responsavel', 'equipe')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (matter_id, user_id),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id) ON DELETE CASCADE,
    -- Only members of the firm can be assigned to its matters.
    FOREIGN KEY (tenant_id, user_id) REFERENCES memberships (tenant_id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE matter_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    kind varchar(50) NOT NULL,
    source varchar(20) NOT NULL DEFAULT 'sistema'
        CHECK (source IN ('manual', 'sistema', 'datajud')),
    actor_user_id uuid,
    summary varchar(500) NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    occurred_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX matter_events_matter_time_idx ON matter_events (matter_id, occurred_at DESC);

CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    title varchar(300) NOT NULL,
    -- Filled by classification in Phase 2b.
    doc_class varchar(50),
    current_version_id uuid,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id)
);
CREATE INDEX documents_matter_idx ON documents (matter_id);

CREATE TABLE document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    document_id uuid NOT NULL,
    version_no integer NOT NULL,
    storage_key varchar(500) NOT NULL UNIQUE,
    original_filename varchar(300) NOT NULL,
    declared_content_type varchar(150),
    detected_type varchar(20),
    size_bytes bigint,
    sha256 char(64),
    page_count integer,
    ocr_page_count integer,
    min_ocr_confidence real,
    status varchar(20) NOT NULL DEFAULT 'pending_upload' CHECK (status IN (
        'pending_upload', 'uploaded', 'processing', 'ready', 'failed', 'rejected')),
    error_code varchar(50),
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    UNIQUE (tenant_id, id),
    UNIQUE (document_id, version_no),
    FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id)
);

ALTER TABLE documents ADD CONSTRAINT documents_current_version_fk
    FOREIGN KEY (tenant_id, current_version_id) REFERENCES document_versions (tenant_id, id);

CREATE TABLE document_pages (
    tenant_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    page_number integer NOT NULL CHECK (page_number >= 1),
    text text NOT NULL,
    method varchar(20) NOT NULL CHECK (method IN ('text_layer', 'ocr', 'docx')),
    -- Mean word confidence from OCR, 0-100. Null when text came from the file itself.
    ocr_confidence real,
    PRIMARY KEY (document_version_id, page_number),
    FOREIGN KEY (tenant_id, document_version_id)
        REFERENCES document_versions (tenant_id, id) ON DELETE CASCADE
);

-- Chunks now belong to a document version and a page span. Phase 1 created this table
-- only for isolation tests; it holds no application data, so NOT NULL is safe here.
ALTER TABLE document_chunks
    ADD COLUMN document_version_id uuid NOT NULL,
    ADD COLUMN page_number integer NOT NULL,
    ADD COLUMN char_start integer NOT NULL,
    ADD COLUMN char_end integer NOT NULL,
    ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', text)) STORED,
    ADD FOREIGN KEY (tenant_id, document_version_id)
        REFERENCES document_versions (tenant_id, id) ON DELETE CASCADE;
CREATE INDEX document_chunks_version_idx ON document_chunks (document_version_id, page_number);
CREATE INDEX document_chunks_tsv_idx ON document_chunks USING gin (tsv);

-- Row-Level Security -------------------------------------------------------------------
"""

TENANT_TABLES = (
    "clients",
    "matters",
    "matter_parties",
    "matter_members",
    "matter_events",
    "documents",
    "document_versions",
    "document_pages",
)

RLS = """
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
CREATE POLICY {t}_tenant ON {t} FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());
"""

GRANTS = """
GRANT SELECT, INSERT, UPDATE, DELETE ON clients, matters, matter_parties, matter_members,
    documents TO {app};
GRANT SELECT, INSERT, UPDATE ON document_versions TO {app};
-- Pages are replaced when a version is reprocessed.
GRANT SELECT, INSERT, DELETE ON document_pages TO {app};
-- The timeline is append-only for the app.
GRANT SELECT, INSERT ON matter_events TO {app};
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TENANT_TABLES:
        op.execute(RLS.format(t=table))
    op.execute(GRANTS.format(app=_app_role()))


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS document_chunks_tsv_idx;
        DROP INDEX IF EXISTS document_chunks_version_idx;
        ALTER TABLE document_chunks
            DROP COLUMN IF EXISTS tsv,
            DROP COLUMN IF EXISTS char_end,
            DROP COLUMN IF EXISTS char_start,
            DROP COLUMN IF EXISTS page_number,
            DROP COLUMN IF EXISTS document_version_id;
        ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_current_version_fk;
        DROP TABLE IF EXISTS document_pages, document_versions, documents, matter_events,
            matter_members, matter_parties, matters, clients;
        """
    )
