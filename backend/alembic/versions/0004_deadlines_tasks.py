"""Deadlines and tasks: holidays, deadline proposals, tasks.

Deadline proposals are never final on their own: a lawyer confirms or rejects each one
(brief rule 5). Holidays are data, not code: system-wide rows (tenant_id NULL) hold the
national fixed-date holidays, and each firm adds its courts' local dates.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


SCHEMA = """
CREATE TABLE holidays (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL = system-wide (national holidays), visible to every firm, editable by none.
    tenant_id uuid REFERENCES tenants(id),
    day date NOT NULL,
    name varchar(200) NOT NULL,
    kind varchar(30) NOT NULL DEFAULT 'feriado'
        CHECK (kind IN ('feriado', 'ponto_facultativo', 'suspensao_expediente')),
    -- Which court/comarca it applies to, free text (e.g. "TJSP - Capital"). Informative.
    scope varchar(120),
    source varchar(300),
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX holidays_unique_day
    ON holidays (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), day);

-- National holidays with a fixed date (VERIFY DL-9 lists the laws to confirm).
INSERT INTO holidays (tenant_id, day, name, source)
SELECT NULL, make_date(y, m, d), name, source
FROM generate_series(2024, 2035) AS y,
     (VALUES
        (1, 1, 'Confraternização Universal', 'Lei 662/1949'),
        (4, 21, 'Tiradentes', 'Lei 662/1949'),
        (5, 1, 'Dia do Trabalho', 'Lei 662/1949'),
        (9, 7, 'Independência do Brasil', 'Lei 662/1949'),
        (10, 12, 'Nossa Senhora Aparecida', 'Lei 6.802/1980'),
        (11, 2, 'Finados', 'Lei 662/1949'),
        (11, 15, 'Proclamação da República', 'Lei 662/1949'),
        (11, 20, 'Dia Nacional de Zumbi e da Consciência Negra', 'Lei 14.759/2023'),
        (12, 25, 'Natal', 'Lei 662/1949')
     ) AS h(m, d, name, source);

CREATE TABLE deadline_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    title varchar(200) NOT NULL,
    rule_set varchar(10) NOT NULL CHECK (rule_set IN ('cpc', 'clt', 'jec')),
    preset_id varchar(50),
    trigger_kind varchar(30) NOT NULL
        CHECK (trigger_kind IN ('disponibilizacao_dje', 'ciencia')),
    trigger_date date NOT NULL,
    days integer NOT NULL CHECK (days BETWEEN 1 AND 3650),
    unit varchar(20) NOT NULL CHECK (unit IN ('dias_uteis', 'dias_corridos')),
    doubled_reason varchar(30),
    proposed_date date NOT NULL,
    -- Step-by-step reasoning shown to the lawyer, as computed at proposal time.
    reasoning jsonb NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'proposto'
        CHECK (status IN ('proposto', 'confirmado', 'rejeitado')),
    -- The date the lawyer confirmed (may differ from the proposal, with a note).
    confirmed_date date,
    decision_note text,
    decided_by uuid,
    decided_at timestamptz,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id),
    CHECK ((status = 'confirmado') = (confirmed_date IS NOT NULL)),
    CHECK ((status = 'proposto') = (decided_by IS NULL))
);
CREATE INDEX deadline_proposals_matter_idx ON deadline_proposals (matter_id, created_at DESC);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    matter_id uuid NOT NULL,
    title varchar(300) NOT NULL,
    due_date date,
    assignee_user_id uuid,
    status varchar(20) NOT NULL DEFAULT 'aberta'
        CHECK (status IN ('aberta', 'concluida', 'cancelada')),
    origin varchar(20) NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'prazo')),
    deadline_proposal_id uuid,
    notes text,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    FOREIGN KEY (tenant_id, matter_id) REFERENCES matters (tenant_id, id),
    FOREIGN KEY (tenant_id, deadline_proposal_id) REFERENCES deadline_proposals (tenant_id, id),
    FOREIGN KEY (tenant_id, assignee_user_id) REFERENCES memberships (tenant_id, user_id)
        ON DELETE SET NULL (assignee_user_id)
);
CREATE INDEX tasks_open_idx ON tasks (tenant_id, due_date) WHERE status = 'aberta';

ALTER TABLE holidays ENABLE ROW LEVEL SECURITY;
CREATE POLICY holidays_read ON holidays FOR SELECT
    USING (tenant_id IS NULL OR tenant_id = app_current_tenant_id());
CREATE POLICY holidays_write ON holidays FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

ALTER TABLE deadline_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY deadline_proposals_tenant ON deadline_proposals FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tasks_tenant ON tasks FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());
"""

GRANTS = """
GRANT SELECT, INSERT, DELETE ON holidays TO {app};
GRANT SELECT, INSERT, UPDATE ON deadline_proposals, tasks TO {app};
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(GRANTS.format(app=_app_role()))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tasks, deadline_proposals, holidays;")
