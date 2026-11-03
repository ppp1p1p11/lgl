"""Foundations: tenants, users, auth, audit log, jobs, document chunks, and RLS.

Tenant isolation (ADR-0002): every firm-scoped table has Row-Level Security enabled.
The application connects as a separate role that owns no table and has no BYPASSRLS,
so it is always subject to these policies. The table owner (this migration's role)
bypasses RLS; it is used only for migrations, provisioning scripts, and the few
SECURITY DEFINER functions below, each of which does one narrow pre-authentication or
queue operation.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


# Tables whose rows belong to exactly one firm, and the privileges the app role gets.
# A test fails if a table with a tenant_id column is missing RLS.
SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

-- Helpers used by RLS policies. An unset value becomes NULL, and `x = NULL` matches nothing,
-- so a query run without a tenant context returns no firm rows (fail closed).
CREATE FUNCTION app_current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app_current_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE TYPE member_role AS ENUM ('socio', 'advogado', 'estagiario', 'administrativo');

CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(200) NOT NULL,
    slug varchar(100) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(320) NOT NULL UNIQUE CHECK (email = lower(email)),
    name varchar(200) NOT NULL,
    password_hash varchar(255) NOT NULL,
    oab_number varchar(20),
    oab_uf char(2),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    user_id uuid NOT NULL REFERENCES users(id),
    role member_role NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
CREATE INDEX memberships_user_id_idx ON memberships (user_id);

CREATE TABLE mfa_factors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    kind varchar(20) NOT NULL DEFAULT 'totp',
    secret_encrypted bytea NOT NULL,
    confirmed_at timestamptz,
    last_used_step integer,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mfa_factors_user_id_idx ON mfa_factors (user_id);

CREATE TABLE mfa_recovery_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    code_hash varchar(255) NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mfa_recovery_codes_user_id_idx ON mfa_recovery_codes (user_id);

CREATE TABLE sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    user_id uuid NOT NULL REFERENCES users(id),
    tenant_id uuid REFERENCES tenants(id),
    mfa_verified boolean NOT NULL DEFAULT false,
    mfa_failures integer NOT NULL DEFAULT 0,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    ip varchar(64),
    user_agent varchar(400),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_id_idx ON sessions (user_id);

CREATE TABLE auth_attempts (
    id bigserial PRIMARY KEY,
    key_hash varchar(64) NOT NULL,
    succeeded boolean NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_attempts_key_idx ON auth_attempts (key_hash, attempted_at);

CREATE TABLE audit_log (
    id bigserial PRIMARY KEY,
    tenant_id uuid REFERENCES tenants(id),
    actor_user_id uuid,
    action varchar(100) NOT NULL,
    entity_type varchar(100),
    entity_id varchar(100),
    ip varchar(64),
    details jsonb NOT NULL DEFAULT '{}',
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_tenant_time_idx ON audit_log (tenant_id, occurred_at DESC);

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id),
    enqueued_by uuid,
    kind varchar(100) NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    status varchar(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'dead')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    run_after timestamptz NOT NULL DEFAULT now(),
    locked_by varchar(100),
    locked_at timestamptz,
    last_error text,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready_idx ON jobs (run_after) WHERE status IN ('queued', 'running');

-- Phase 1 keeps only what the isolation tests need; Phase 2 adds document versions and
-- spans, and the embedding dimension + ANN index once the model is chosen (VERIFY AI-3).
CREATE TABLE document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    text text NOT NULL,
    embedding vector,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX document_chunks_tenant_idx ON document_chunks (tenant_id);

-- Row-Level Security --------------------------------------------------------------------

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenants_member_read ON tenants FOR SELECT USING (
    id = app_current_tenant_id()
    OR id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = app_current_user_id())
);
CREATE POLICY tenants_update ON tenants FOR UPDATE USING (id = app_current_tenant_id());

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
-- A user sees every member of the current firm, and their own memberships in other firms
-- (needed for the firm switcher).
CREATE POLICY memberships_read ON memberships FOR SELECT USING (
    tenant_id = app_current_tenant_id() OR user_id = app_current_user_id()
);
CREATE POLICY memberships_write ON memberships FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- Users are not firm-scoped (one person can belong to two firms), but the app may only see
-- itself and members of the current firm. Login lookups go through auth_lookup_user().
CREATE POLICY users_read ON users FOR SELECT USING (
    id = app_current_user_id()
    OR EXISTS (
        SELECT 1 FROM memberships m
        WHERE m.user_id = users.id AND m.tenant_id = app_current_tenant_id()
    )
);
CREATE POLICY users_update_self ON users FOR UPDATE USING (id = app_current_user_id());

ALTER TABLE mfa_factors ENABLE ROW LEVEL SECURITY;
CREATE POLICY mfa_factors_own ON mfa_factors FOR ALL
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());

ALTER TABLE mfa_recovery_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY mfa_recovery_codes_own ON mfa_recovery_codes FOR ALL
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY sessions_own ON sessions FOR ALL
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_log_read ON audit_log FOR SELECT USING (tenant_id = app_current_tenant_id());
CREATE POLICY audit_log_insert ON audit_log FOR INSERT WITH CHECK (
    tenant_id IS NULL OR tenant_id = app_current_tenant_id()
);

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_tenant ON jobs FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_chunks_tenant ON document_chunks FOR ALL
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

-- Narrow SECURITY DEFINER functions (run as the owner, so they bypass RLS) -------------

-- Login: find a user by email before anyone is authenticated.
CREATE FUNCTION auth_lookup_user(p_email text)
    RETURNS TABLE (id uuid, password_hash text, is_active boolean)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$ SELECT u.id, u.password_hash, u.is_active FROM users u WHERE u.email = lower(p_email) $$;

-- Every request: resolve the session cookie (by token hash) to a user and firm.
CREATE FUNCTION auth_lookup_session(p_token_hash bytea)
    RETURNS TABLE (
        id uuid, user_id uuid, tenant_id uuid, mfa_verified boolean,
        mfa_failures integer, expires_at timestamptz
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        SELECT s.id, s.user_id, s.tenant_id, s.mfa_verified, s.mfa_failures, s.expires_at
        FROM sessions s
        WHERE s.token_hash = p_token_hash AND s.revoked_at IS NULL AND s.expires_at > now()
    $$;

-- Worker: claim the next ready job from any firm. Jobs stuck in 'running' for longer than
-- the lease (e.g. a worker crashed) become claimable again.
CREATE FUNCTION jobs_claim(p_worker text, p_lease_seconds integer)
    RETURNS SETOF jobs
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        UPDATE jobs SET status = 'running', locked_by = p_worker, locked_at = now(),
                        attempts = attempts + 1
        WHERE id = (
            SELECT j.id FROM jobs j
            WHERE (j.status = 'queued' AND j.run_after <= now())
               OR (j.status = 'running'
                   AND j.locked_at < now() - make_interval(secs => p_lease_seconds))
            ORDER BY j.run_after
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    $$;

-- Worker: record a job's outcome. Retries with the given delay until max_attempts.
CREATE FUNCTION jobs_finish(
    p_job_id uuid, p_worker text, p_error text, p_retry_delay_seconds integer
) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        UPDATE jobs SET
            status = CASE
                WHEN p_error IS NULL THEN 'succeeded'
                WHEN attempts >= max_attempts THEN 'dead'
                ELSE 'queued' END,
            run_after = CASE WHEN p_error IS NULL THEN run_after
                ELSE now() + make_interval(secs => p_retry_delay_seconds) END,
            finished_at = CASE WHEN p_error IS NULL OR attempts >= max_attempts
                THEN now() END,
            last_error = p_error,
            locked_by = NULL,
            locked_at = NULL
        WHERE id = p_job_id AND locked_by = p_worker
    $$;
"""

GRANTS = """
GRANT USAGE ON SCHEMA public TO {app};
GRANT SELECT, UPDATE ON tenants TO {app};
GRANT SELECT, UPDATE ON users TO {app};
GRANT SELECT, INSERT, UPDATE, DELETE ON memberships, mfa_factors, mfa_recovery_codes,
    sessions, document_chunks TO {app};
GRANT SELECT, INSERT, DELETE ON auth_attempts TO {app};
GRANT USAGE ON SEQUENCE auth_attempts_id_seq TO {app};
-- Audit log is append-only for the app.
GRANT SELECT, INSERT ON audit_log TO {app};
GRANT USAGE ON SEQUENCE audit_log_id_seq TO {app};
-- Jobs: the app enqueues and reads its firm's jobs; state changes go through functions.
GRANT SELECT, INSERT ON jobs TO {app};

REVOKE EXECUTE ON FUNCTION auth_lookup_user(text), auth_lookup_session(bytea),
    jobs_claim(text, integer), jobs_finish(uuid, text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_user(text), auth_lookup_session(bytea),
    jobs_claim(text, integer), jobs_finish(uuid, text, text, integer) TO {app};
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(GRANTS.format(app=_app_role()))


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS jobs_finish(uuid, text, text, integer);
        DROP FUNCTION IF EXISTS jobs_claim(text, integer);
        DROP FUNCTION IF EXISTS auth_lookup_session(bytea);
        DROP FUNCTION IF EXISTS auth_lookup_user(text);
        DROP TABLE IF EXISTS document_chunks, jobs, audit_log, auth_attempts, sessions,
            mfa_recovery_codes, mfa_factors, memberships, users, tenants;
        DROP TYPE IF EXISTS member_role;
        DROP FUNCTION IF EXISTS app_current_tenant_id();
        DROP FUNCTION IF EXISTS app_current_user_id();
        """
    )
