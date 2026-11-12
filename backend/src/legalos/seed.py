"""Seed fictional firms and users for local development and demos.

Usage: python -m legalos.seed
Runs as the owner role (provisioning), refuses to run in production, and is idempotent.
All names, emails and OAB numbers are fictional. Every user's password is
`DEV_PASSWORD` below; MFA is set up on first login.
"""

import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from legalos.auth.models import User
from legalos.config import get_settings
from legalos.core.crypto import hash_password
from legalos.tenancy.models import Membership, Tenant
from legalos.tenancy.roles import Role

DEV_PASSWORD = "senha-de-teste-123"  # noqa: S105 - fictional dev-only credential


@dataclass(frozen=True)
class SeedUser:
    email: str
    name: str
    role: Role
    oab: tuple[str, str] | None = None


@dataclass(frozen=True)
class SeedFirm:
    slug: str
    name: str
    users: tuple[SeedUser, ...]


FIRMS = (
    SeedFirm(
        slug="silva-associados",
        name="Silva & Associados Advocacia (fictício)",
        users=(
            SeedUser("ana.silva@silva.example", "Ana Silva", Role.SOCIO, ("123456", "SP")),
            SeedUser("bruno.costa@silva.example", "Bruno Costa", Role.ADVOGADO, ("234567", "SP")),
            SeedUser("carla.dias@silva.example", "Carla Dias", Role.ESTAGIARIO),
            SeedUser("diego.alves@silva.example", "Diego Alves", Role.ADMINISTRATIVO),
        ),
    ),
    SeedFirm(
        slug="oliveira-trabalhista",
        name="Oliveira Advocacia Trabalhista (fictício)",
        users=(
            SeedUser(
                "eduarda.oliveira@oliveira.example",
                "Eduarda Oliveira",
                Role.SOCIO,
                ("345678", "RJ"),
            ),
            SeedUser("fabio.lima@oliveira.example", "Fábio Lima", Role.ADVOGADO, ("456789", "RJ")),
        ),
    ),
    SeedFirm(
        slug="pereira-consumidor",
        name="Pereira Direito do Consumidor (fictício)",
        users=(
            SeedUser(
                "gabriela.pereira@pereira.example", "Gabriela Pereira", Role.SOCIO, ("567890", "MG")
            ),
            # Also an associate at Silva & Associados, to exercise the firm switcher.
            SeedUser("bruno.costa@silva.example", "Bruno Costa", Role.ADVOGADO, ("234567", "SP")),
        ),
    ),
)


def seed(db: Session) -> None:
    password_hash = hash_password(DEV_PASSWORD)
    for firm in FIRMS:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == firm.slug))
        if tenant is None:
            tenant = Tenant(id=uuid.uuid4(), slug=firm.slug, name=firm.name)
            db.add(tenant)
            db.flush()
        for su in firm.users:
            user = db.scalar(select(User).where(User.email == su.email))
            if user is None:
                user = User(
                    id=uuid.uuid4(),
                    email=su.email,
                    name=su.name,
                    password_hash=password_hash,
                    oab_number=su.oab[0] if su.oab else None,
                    oab_uf=su.oab[1] if su.oab else None,
                )
                db.add(user)
                db.flush()
            if db.get(Membership, (tenant.id, user.id)) is None:
                db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=su.role))
    db.flush()


def main() -> None:
    settings = get_settings()
    if settings.environment == "production":
        sys.exit("Refusing to seed fictional data in production.")
    engine = create_engine(settings.database_owner_url.get_secret_value())
    with Session(engine) as db, db.begin():
        seed(db)
    engine.dispose()
    print(f"Seeded fictional firms. Users (password for all: {DEV_PASSWORD}):")
    for firm in FIRMS:
        for su in firm.users:
            print(f"  {firm.slug:22} {su.role.value:15} {su.email}")


if __name__ == "__main__":
    main()
