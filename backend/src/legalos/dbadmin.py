"""One-time database bootstrap, run with superuser credentials.

Creates the two roles used by the system and the database:
- the owner role, which owns every table and runs migrations and provisioning scripts;
- the app role, used by the API and worker: owns nothing, cannot bypass RLS.

Usage: python -m legalos.dbadmin   (reads LEGALOS_DB_ADMIN_URL and the role URLs)
Idempotent: safe to run more than once.
"""

import os
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url


def _connect(url: URL, database: str | None = None) -> psycopg.Connection:
    return psycopg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname=database or url.database,
        autocommit=True,
    )


def bootstrap(admin_url: str, owner_url: str, app_url: str) -> None:
    admin = make_url(admin_url)
    owner = make_url(owner_url)
    app = make_url(app_url)
    if owner.database != app.database or not owner.database:
        raise ValueError("Owner and app URLs must point to the same database")
    db = sql.Identifier(owner.database)
    owner_role = sql.Identifier(owner.username or "")
    app_role = sql.Identifier(app.username or "")

    with _connect(admin) as conn:
        roles = (
            (owner, sql.SQL("")),
            (app, sql.SQL(" NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")),
        )
        for url, attrs in roles:
            exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (url.username,)
            ).fetchone()
            verb = sql.SQL("ALTER" if exists else "CREATE")
            conn.execute(
                sql.SQL("{} ROLE {} LOGIN PASSWORD {}{}").format(
                    verb, sql.Identifier(url.username or ""), sql.Literal(url.password), attrs
                )
            )
        if not conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (owner.database,)
        ).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(db, owner_role))

    # pgvector must be created by a superuser (it is not a "trusted" extension).
    with _connect(admin, owner.database) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, app_role))
        conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner_role))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


def main() -> None:
    try:
        admin_url = os.environ["LEGALOS_DB_ADMIN_URL"]
        owner_url = os.environ["LEGALOS_DATABASE_OWNER_URL"]
        app_url = os.environ["LEGALOS_DATABASE_URL"]
    except KeyError as missing:
        sys.exit(f"Missing environment variable: {missing}")
    bootstrap(admin_url, owner_url, app_url)
    print("Database roles and database are ready.")


if __name__ == "__main__":
    main()
