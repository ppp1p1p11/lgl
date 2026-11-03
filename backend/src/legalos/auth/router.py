import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from legalos.auth import service
from legalos.auth.deps import (
    SESSION_COOKIE,
    AnyPrincipal,
    CurrentPrincipal,
    DbSession,
    client_ip,
)
from legalos.auth.models import User
from legalos.config import get_settings
from legalos.tenancy.roles import ROLE_PERMISSIONS, Permission, Role

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    next_step: service.LoginNextStep


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaConfirmResponse(BaseModel):
    recovery_codes: list[str]


class MfaVerifyRequest(BaseModel):
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, max_length=40)


class SwitchFirmRequest(BaseModel):
    tenant_id: uuid.UUID


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class FirmOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class MeResponse(BaseModel):
    user: UserOut
    mfa_verified: bool
    current_firm: FirmOut | None
    permissions: list[Permission]
    firms: list[FirmOut]


def _raise(error: service.AuthError) -> None:
    raise HTTPException(error.status_code, error.code.value) from error


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> LoginResponse:
    try:
        result = service.login(
            db,
            email=body.email,
            password=body.password,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except service.AuthError as e:
        _raise(e)
    _set_session_cookie(response, result.token)
    return LoginResponse(next_step=result.next_step)


@router.post("/mfa/setup")
def mfa_setup(principal: AnyPrincipal, db: DbSession) -> MfaSetupResponse:
    try:
        setup = service.start_mfa_setup(db, principal)
    except service.AuthError as e:
        _raise(e)
    return MfaSetupResponse(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post("/mfa/confirm")
def mfa_confirm(
    body: MfaCodeRequest, request: Request, principal: AnyPrincipal, db: DbSession
) -> MfaConfirmResponse:
    try:
        codes = service.confirm_mfa_setup(db, principal, body.code, ip=client_ip(request))
    except service.AuthError as e:
        _raise(e)
    return MfaConfirmResponse(recovery_codes=codes)


@router.post("/mfa/verify", status_code=204)
def mfa_verify(
    body: MfaVerifyRequest, request: Request, principal: AnyPrincipal, db: DbSession
) -> None:
    try:
        service.verify_mfa(
            db,
            principal,
            code=body.code,
            recovery_code=body.recovery_code,
            ip=client_ip(request),
        )
    except service.AuthError as e:
        _raise(e)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, principal: AnyPrincipal, db: DbSession) -> None:
    service.logout(db, principal, ip=client_ip(request))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(principal: AnyPrincipal, db: DbSession) -> MeResponse:
    user = db.get(User, principal.user_id)
    assert user is not None
    firms = (
        [FirmOut(id=f.id, name=f.name, role=f.role) for f in service.list_my_firms(db, user.id)]
        if principal.mfa_verified
        else []
    )
    current = next((f for f in firms if f.id == principal.tenant_id), None)
    permissions = sorted(ROLE_PERMISSIONS[current.role]) if current else []
    return MeResponse(
        user=UserOut(id=user.id, name=user.name, email=user.email),
        mfa_verified=principal.mfa_verified,
        current_firm=current,
        permissions=permissions,
        firms=firms,
    )


@router.post("/switch-firm", status_code=204)
def switch_firm(
    body: SwitchFirmRequest, request: Request, principal: CurrentPrincipal, db: DbSession
) -> None:
    try:
        service.switch_tenant(db, principal, body.tenant_id, ip=client_ip(request))
    except service.AuthError as e:
        _raise(e)
