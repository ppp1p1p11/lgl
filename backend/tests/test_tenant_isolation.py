"""Brief rule 7 / ADR-0002: tenant A can never read or change tenant B's data.

These tests deliberately query *without* any tenant filter in application code, to prove
that the database itself (Row-Level Security) enforces isolation.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.audit.service import record
from legalos.auth.models import User
from legalos.documents.models import DocumentChunk
from legalos.jobs.models import Job
from legalos.jobs.queue import enqueue
from legalos.tenancy.models import Membership, Tenant
from legalos.tenancy.roles import Role
from tests.conftest import app_db, login_with_mfa

# Tables that intentionally have no RLS: they hold no firm data.
TABLES_WITHOUT_RLS = {"alembic_version", "auth_attempts"}


@pytest.fixture
def two_firms(make_firm, make_member, make_version, owner_engine: Engine):
    a, b = make_firm("Alfa"), make_firm("Beta")
    member_a, member_b = make_member(a), make_member(b)
    version_a, version_b = make_version(a), make_version(b)
    # Tenant B's chunk is the *closest* match to the query vector used below, so a leak
    # would show up first in the results.
    with Session(owner_engine) as db, db.begin():
        db.add_all(
            [
                _chunk(a, version_a, "contrato de locação Alfa", [1, 0, 0]),
                _chunk(a, version_a, "petição inicial Alfa", [0, 1, 0]),
                _chunk(b, version_b, "segredo do cliente Beta", [0, 0, 1]),
            ]
        )
    return a, b, member_a, member_b


def _chunk(tenant_id, version_id, text_, embedding) -> DocumentChunk:
    return DocumentChunk(
        tenant_id=tenant_id,
        document_version_id=version_id,
        page_number=1,
        char_start=0,
        char_end=len(text_),
        text=text_,
        embedding=embedding,
    )


# --- Database configuration ---------------------------------------------------------------


def test_app_role_cannot_bypass_rls(owner_engine: Engine) -> None:
    with app_db() as db:
        role = db.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        owned = db.scalar(
            text(
                "SELECT count(*) FROM pg_tables"
                " WHERE schemaname = 'public' AND tableowner = current_user"
            )
        )
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert owned == 0, "The app role must not own tables (owners bypass RLS)"


def test_every_table_has_rls_enabled(owner_db: Session) -> None:
    rows = owner_db.execute(
        text(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r'"
        )
    ).all()
    missing = {r.relname for r in rows if not r.relrowsecurity} - TABLES_WITHOUT_RLS
    assert not missing, f"Tables without Row-Level Security: {missing}"


def test_every_tenant_table_has_rls(owner_db: Session) -> None:
    rows = owner_db.execute(
        text(
            "SELECT c.table_name, t.relrowsecurity FROM information_schema.columns c "
            "JOIN pg_class t ON t.relname = c.table_name "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'"
        )
    ).all()
    assert rows, "expected tenant-scoped tables"
    assert all(r.relrowsecurity for r in rows), [r.table_name for r in rows]


# --- Direct database access as the app role -----------------------------------------------


def test_reads_without_filter_only_see_own_tenant(two_firms) -> None:
    a, _b, *_ = two_firms
    with app_db(tenant_id=a) as db:
        texts = db.scalars(select(DocumentChunk.text)).all()
    assert sorted(texts) == ["contrato de locação Alfa", "petição inicial Alfa"]


def test_vector_search_never_returns_other_tenant(two_firms) -> None:
    a, _b, *_ = two_firms
    query = [0.0, 0.0, 1.0]  # identical to tenant B's chunk
    with app_db(tenant_id=a) as db:
        results = db.scalars(
            select(DocumentChunk).order_by(DocumentChunk.embedding.l2_distance(query)).limit(10)
        ).all()
        raw = (
            db.execute(
                text(
                    "SELECT tenant_id FROM document_chunks"
                    " ORDER BY embedding <=> '[0,0,1]' LIMIT 10"
                )
            )
            .scalars()
            .all()
        )
    assert results and {r.tenant_id for r in results} == {a}
    assert set(raw) == {a}


def test_no_tenant_context_sees_nothing(two_firms) -> None:
    with app_db() as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
        assert db.scalar(select(func.count()).select_from(Tenant)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(Membership)) == 0


def test_cannot_insert_into_other_tenant(two_firms, owner_db: Session) -> None:
    a, b, *_ = two_firms
    version_b = owner_db.scalar(
        select(DocumentChunk.document_version_id).where(DocumentChunk.tenant_id == b)
    )
    with pytest.raises(ProgrammingError, match="row-level security"), app_db(tenant_id=a) as db:
        db.add(_chunk(b, version_b, "injected", [1, 1, 1]))
        db.flush()


def test_cannot_update_or_delete_other_tenant(two_firms, owner_db: Session) -> None:
    a, b, *_ = two_firms
    with app_db(tenant_id=a) as db:
        updated = db.execute(
            update(DocumentChunk).where(DocumentChunk.tenant_id == b).values(text="hacked")
        ).rowcount
        deleted = db.execute(delete(DocumentChunk).where(DocumentChunk.tenant_id == b)).rowcount
        # Even an unfiltered update can only touch the own firm's rows.
        db.execute(update(DocumentChunk).values(text="mine"))
    assert updated == 0 and deleted == 0
    owner_db.expire_all()
    assert owner_db.scalar(select(DocumentChunk.text).where(DocumentChunk.tenant_id == b)) == (
        "segredo do cliente Beta"
    )


def test_cannot_move_row_to_other_tenant(two_firms) -> None:
    a, b, *_ = two_firms
    with pytest.raises(ProgrammingError, match="row-level security"), app_db(tenant_id=a) as db:
        db.execute(update(DocumentChunk).values(tenant_id=b))


def test_users_and_memberships_of_other_firm_are_invisible(two_firms) -> None:
    a, _b, member_a, _member_b = two_firms
    with app_db(tenant_id=a, user_id=member_a.user_id) as db:
        emails = set(db.scalars(select(User.email)).all())
        firm_ids = set(db.scalars(select(Tenant.id)).all())
        membership_firms = set(db.scalars(select(Membership.tenant_id)).all())
    assert emails == {member_a.email}
    assert firm_ids == {a}
    assert membership_firms == {a}


def test_audit_log_and_jobs_are_isolated(two_firms) -> None:
    a, b, member_a, member_b = two_firms
    with app_db(tenant_id=b, user_id=member_b.user_id) as db:
        record(db, "test.event", tenant_id=b, actor_user_id=member_b.user_id)
        enqueue(db, "system.ping", tenant_id=b)
    with app_db(tenant_id=a, user_id=member_a.user_id) as db:
        assert db.scalars(select(AuditEvent)).all() == []
        assert db.scalars(select(Job)).all() == []
        with pytest.raises(ProgrammingError, match="row-level security"):
            record(db, "forged", tenant_id=b, actor_user_id=member_a.user_id)


def test_tenant_context_does_not_leak_between_transactions(two_firms) -> None:
    a, *_ = two_firms
    with app_db(tenant_id=a) as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 2
    # Same pool, new transaction, no context: must see nothing.
    with app_db() as db:
        assert db.scalar(text("SELECT current_setting('app.tenant_id', true)")) in ("", None)
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0


# --- Through the API ----------------------------------------------------------------------


def test_api_members_list_is_isolated(client: TestClient, make_firm, make_member) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    socio_a = make_member(a, Role.SOCIO)
    colleague = make_member(a, Role.ADVOGADO)
    make_member(b, Role.SOCIO)
    login_with_mfa(client, socio_a.email)
    emails = {m["email"] for m in client.get("/api/firm/members").json()}
    assert emails == {socio_a.email, colleague.email}


def test_api_audit_log_is_isolated(client: TestClient, make_firm, make_member) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    socio_a, socio_b = make_member(a), make_member(b)
    login_with_mfa(client, socio_b.email)
    client.post("/api/auth/logout")
    login_with_mfa(client, socio_a.email)
    events = client.get("/api/audit-log").json()
    assert events
    assert all(e["actor_user_id"] in (str(socio_a.user_id), None) for e in events)


def test_api_cannot_switch_to_foreign_firm(client: TestClient, make_firm, make_member) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    socio_a = make_member(a)
    login_with_mfa(client, socio_a.email)
    r = client.post("/api/auth/switch-firm", json={"tenant_id": str(b)})
    assert r.status_code == 403
    r = client.post("/api/auth/switch-firm", json={"tenant_id": str(uuid.uuid4())})
    assert r.status_code == 403
