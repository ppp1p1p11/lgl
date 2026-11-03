"""FastAPI dependencies that authenticate the request and enforce roles."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from legalos.auth.service import AuthErrorCode, Principal, resolve_session
from legalos.core.db import get_db
from legalos.tenancy.roles import Permission, Role, has_permission

SESSION_COOKIE = "legalos_session"

DbSession = Annotated[Session, Depends(get_db, scope="function")]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_any_principal(request: Request, db: DbSession) -> Principal:
    """Any valid session, including one still waiting for MFA."""
    principal = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise HTTPException(401, AuthErrorCode.NOT_AUTHENTICATED)
    return principal


AnyPrincipal = Annotated[Principal, Depends(get_any_principal)]


def get_principal(principal: AnyPrincipal) -> Principal:
    """A fully authenticated session (password + MFA)."""
    if not principal.mfa_verified:
        raise HTTPException(401, AuthErrorCode.MFA_REQUIRED)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def get_firm_principal(principal: CurrentPrincipal) -> Principal:
    if principal.tenant_id is None or principal.role is None:
        raise HTTPException(403, AuthErrorCode.NO_FIRM_SELECTED)
    return principal


CurrentFirmPrincipal = Annotated[Principal, Depends(get_firm_principal)]


def require(permission: Permission) -> Callable[[Principal], Principal]:
    """Dependency factory: `Depends(require(Permission.VIEW_AUDIT_LOG))`."""

    def checker(principal: CurrentFirmPrincipal) -> Principal:
        assert principal.role is not None
        if not has_permission(Role(principal.role), permission):
            raise HTTPException(403, AuthErrorCode.FORBIDDEN)
        return principal

    return checker
