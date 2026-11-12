"""Team management: sócios can add people to the firm; temporary passwords.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

import re
from collections.abc import Sequence

from alembic import op

from legalos.config import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = get_settings().database_app_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise ValueError(f"Invalid app role name: {role!r}")
    return role


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE users ADD COLUMN must_change_password boolean NOT NULL DEFAULT false;
        -- A new account can only be created from inside a firm (by a sócio; the API checks
        -- the role). It becomes visible to that firm once its membership row exists.
        CREATE POLICY users_insert ON users FOR INSERT
            WITH CHECK (app_current_tenant_id() IS NOT NULL);
        GRANT INSERT ON users TO {_app_role()};
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        REVOKE INSERT ON users FROM {_app_role()};
        DROP POLICY IF EXISTS users_insert ON users;
        ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
        """
    )
