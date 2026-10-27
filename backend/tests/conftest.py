"""Test setup: a real PostgreSQL + pgvector database (RLS cannot be tested on SQLite).

Requires a Postgres superuser URL in LEGALOS_TEST_ADMIN_URL (default: local postgres).
A fresh `legalos_test` database is created per test session and wiped between tests.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from cryptography.fernet import Fernet

ADMIN_URL = os.environ.get(
    "LEGALOS_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
_TEST_DB = "legalos_test"
_host = ADMIN_URL.split("@", 1)[1].split("/", 1)[0]
OWNER_URL = f"postgresql+psycopg://legalos_test_owner:test_owner_pw@{_host}/{_TEST_DB}"
APP_URL = f"postgresql+psycopg://legalos_test_app:test_app_pw@{_host}/{_TEST_DB}"

# Settings are read once (cached), so the environment must be set before importing legalos.
os.environ.update(
    {
        "LEGALOS_ENVIRONMENT": "test",
        "LEGALOS_DATABASE_URL": APP_URL,
        "LEGALOS_DATABASE_OWNER_URL": OWNER_URL,
        "LEGALOS_DATABASE_APP_ROLE": "legalos_test_app",
        "LEGALOS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "LEGALOS_SESSION_COOKIE_SECURE": "false",
        "LEGALOS_STORAGE_ACCESS_KEY": "test-access-key",
        "LEGALOS_STORAGE_SECRET_KEY": "test-secret-key",
    }
)

import psycopg  # noqa: E402
import pyotp  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from legalos.auth.models import User  # noqa: E402
from legalos.core.crypto import hash_password  # noqa: E402
from legalos.core.db import get_engine, get_sessionmaker, set_db_context  # noqa: E402
from legalos.dbadmin import bootstrap  # noqa: E402
from legalos.tenancy.models import Membership, Tenant  # noqa: E402
from legalos.tenancy.roles import Role  # noqa: E402

PASSWORD = "uma-senha-de-teste"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB} WITH (FORCE)")
    bootstrap(ADMIN_URL, OWNER_URL, APP_URL)
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.attributes["database_url"] = OWNER_URL
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(scope="session")
def owner_engine(database: None) -> Iterator[Engine]:
    engine = create_engine(OWNER_URL)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(owner_engine: Engine) -> None:
    with owner_engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def owner_db(owner_engine: Engine) -> Iterator[Session]:
    """A session as the table owner (bypasses RLS) for arranging and inspecting data."""
    with Session(owner_engine) as db, db.begin():
        yield db


@contextmanager
def app_db(
    *, tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> Iterator[Session]:
    """A session as the restricted app role, with the given tenant context."""
    with get_sessionmaker()() as db, db.begin():
        set_db_context(db, user_id=user_id, tenant_id=tenant_id)
        yield db


@dataclass(frozen=True)
class Member:
    user_id: uuid.UUID
    email: str
    tenant_id: uuid.UUID
    role: Role


@pytest.fixture
def make_firm(owner_engine: Engine) -> Callable[[str], uuid.UUID]:
    def _make(name: str) -> uuid.UUID:
        tenant_id = uuid.uuid4()
        with Session(owner_engine) as db, db.begin():
            db.add(Tenant(id=tenant_id, name=name, slug=f"{name.lower()}-{tenant_id.hex[:6]}"))
        return tenant_id

    return _make


@pytest.fixture
def make_member(owner_engine: Engine) -> Callable[..., Member]:
    password_hash = hash_password(PASSWORD)

    def _make(tenant_id: uuid.UUID, role: Role = Role.SOCIO, email: str | None = None) -> Member:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        with Session(owner_engine) as db, db.begin():
            user = db.query(User).filter_by(email=email).one_or_none()
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    name=email.split("@")[0],
                    password_hash=password_hash,
                )
                db.add(user)
                db.flush()
            db.add(Membership(tenant_id=tenant_id, user_id=user.id, role=role))
            user_id = user.id
        return Member(user_id=user_id, email=email, tenant_id=tenant_id, role=role)

    return _make


@pytest.fixture
def client() -> Iterator[TestClient]:
    from legalos.main import app

    with TestClient(app) as c:
        yield c


def totp_now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def login_with_mfa(client: TestClient, email: str, password: str = PASSWORD) -> str:
    """Log in and enroll MFA. Returns the TOTP secret."""
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert r.json()["next_step"] == "mfa_setup"
    secret = client.post("/api/auth/mfa/setup").json()["secret"]
    r = client.post("/api/auth/mfa/confirm", json={"code": totp_now(secret)})
    assert r.status_code == 200, r.text
    return str(secret)
