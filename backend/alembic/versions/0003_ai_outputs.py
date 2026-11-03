"""AI on documents: runs, outputs, versions, citations, approvals, gateway call log.

AI outputs are drafts until a lawyer approves a specific version (brief rule 2).
Versions, citations, approvals and the gateway log are append-only for the app.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


SCHEMA = """
-- Per-firm AI policy (set by a sócio).
ALTER TABLE tenants
    ADD COLUMN ai_monthly_budget_usd numeric(10, 2) NOT NULL DEFAULT 50,
    ADD COLUMN ai_redaction_enabled boolean NOT NULL DEFAULT true;

ALTER TABLE documents
    ADD COLUMN doc_class_source varchar(10) CHECK (doc_class_source IN ('ai', 'user'));

CREATE TABLE ai_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    workflow varchar(30) NOT NULL CHECK (workflow IN ('document_analysis')),
    status varchar(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    error_code varchar(50),
    started_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id),
    FOREIGN KEY (tenant_id, document_version_id) REFERENCES document_versions (tenant_id, id)
);
CREATE INDEX ai_runs_version_idx ON ai_runs (document_version_id, created_at DESC);

CREATE TABLE gateway_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    ai_run_id uuid,
    user_id uuid,
    purpose varchar(50) NOT NULL,
    provider varchar(30) NOT NULL,
    model varchar(80) NOT NULL,
    status varchar(20) NOT NULL CHECK (status IN ('ok', 'refused', 'truncated', 'error')),
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cache_write_tokens integer NOT NULL DEFAULT 0,
    cache_read_tokens integer NOT NULL DEFAULT 0,
    cost_usd numeric(12, 6) NOT NULL DEFAULT 0,
    latency_ms integer,
    redaction_count integer NOT NULL DEFAULT 0,
    request_id varchar(100),
    -- Raw prompts and responses are never stored here (brief §4).
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, ai_run_id) REFERENCES ai_runs (tenant_id, id)
);
CREATE INDEX gateway_calls_tenant_month_idx ON gateway_calls (tenant_id, created_at);

CREATE TABLE ai_outputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    ai_run_id uuid NOT NULL,
    kind varchar(30) NOT NULL CHECK (kind IN ('facts', 'summary')),
    status varchar(20) NOT NULL DEFAULT 'rascunho'
        CHECK (status IN ('rascunho', 'em_revisao', 'aprovado', 'rejeitado')),
    current_version_no integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id),
    FOREIGN KEY (tenant_id, document_version_id) REFERENCES document_versions (tenant_id, id),
    FOREIGN KEY (tenant_id, ai_run_id) REFERENCES ai_runs (tenant_id, id)
);
CREATE INDEX ai_outputs_version_idx ON ai_outputs (document_version_id, created_at DESC);

CREATE TABLE ai_output_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    ai_output_id uuid NOT NULL,
    version_no integer NOT NULL,
    content jsonb NOT NULL,
    created_by_ai boolean NOT NULL,
    created_by uuid,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    UNIQUE (ai_output_id, version_no),
    FOREIGN KEY (tenant_id, ai_output_id) REFERENCES ai_outputs (tenant_id, id)
);

CREATE TABLE ai_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    ai_output_version_id uuid NOT NULL,
    -- Position of the cited item inside the version content (fact or summary segment).
    item_index integer NOT NULL,
    document_version_id uuid NOT NULL,
    page_number integer,
    char_start integer,
    char_end integer,
    quoted_text text NOT NULL,
    verification varchar(20) NOT NULL CHECK (verification IN ('verificado', 'nao_verificado')),
    FOREIGN KEY (tenant_id, ai_output_version_id)
        REFERENCES ai_output_versions (tenant_id, id),
    FOREIGN KEY (tenant_id, document_version_id) REFERENCES document_versions (tenant_id, id)
);
CREATE INDEX ai_citations_version_idx ON ai_citations (ai_output_version_id);

CREATE TABLE ai_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    ai_output_version_id uuid NOT NULL,
    approver_user_id uuid NOT NULL,
    decision varchar(20) NOT NULL CHECK (decision IN ('aprovado', 'rejeitado')),
    comment text,
    decided_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, ai_output_version_id)
        REFERENCES ai_output_versions (tenant_id, id),
    FOREIGN KEY (tenant_id, approver_user_id) REFERENCES memberships (tenant_id, user_id)
);
"""

TENANT_TABLES = (
    "ai_runs",
    "gateway_calls",
    "ai_outputs",
    "ai_output_versions",
    "ai_citations",
    "ai_approvals",
)

RLS = """
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
CREATE POLICY {t}_tenant ON {t} FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());
"""

GRANTS = """
GRANT SELECT, INSERT, UPDATE ON ai_runs, ai_outputs TO {app};
-- History is append-only: versions, citations, approvals and the cost log.
GRANT SELECT, INSERT ON ai_output_versions, ai_citations, ai_approvals, gateway_calls TO {app};
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TENANT_TABLES:
        op.execute(RLS.format(t=table))
    op.execute(GRANTS.format(app=_app_role()))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS ai_approvals, ai_citations, ai_output_versions, ai_outputs,
            gateway_calls, ai_runs;
        ALTER TABLE documents DROP COLUMN IF EXISTS doc_class_source;
        ALTER TABLE tenants
            DROP COLUMN IF EXISTS ai_redaction_enabled,
            DROP COLUMN IF EXISTS ai_monthly_budget_usd;
        """
    )
