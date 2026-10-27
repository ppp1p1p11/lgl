"""Login, MFA, sessions and firm switching (ADR-0003).

Flow:
1. `login` checks email + password and creates a session that is *pending MFA*.
2. If the user has no authenticator yet: `start_mfa_setup` then `confirm_mfa_setup`.
   Otherwise: `verify_mfa` with a TOTP code or a one-time recovery code.
3. Only an MFA-verified session can reach firm data.
"""

import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pyotp
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from legalos.audit.service import record, record_independently
from legalos.auth.models import AuthAttempt, AuthSession, MfaFactor, RecoveryCode, User
from legalos.config import get_settings
from legalos.core import crypto
from legalos.core.db import independent_transaction, set_db_context
from legalos.tenancy.models import Membership, Tenant
from legalos.tenancy.roles import Role

TOTP_ISSUER = "LegalOS Brasil"
TOTP_STEP_SECONDS = 30
RECOVERY_CODE_COUNT = 10


class AuthErrorCode(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    NOT_AUTHENTICATED = "not_authenticated"
    MFA_REQUIRED = "mfa_required"
    MFA_ALREADY_CONFIGURED = "mfa_already_configured"
    MFA_SETUP_NOT_STARTED = "mfa_setup_not_started"
    INVALID_MFA_CODE = "invalid_mfa_code"
    NO_FIRM_SELECTED = "no_firm_selected"
    NOT_A_MEMBER = "not_a_member"
    FORBIDDEN = "forbidden"


class AuthError(Exception):
    def __init__(self, code: AuthErrorCode, status_code: int) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    """Who is making the request, resolved from the session cookie."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    mfa_verified: bool
    tenant_id: uuid.UUID | None
    role: Role | None


class LoginNextStep(StrEnum):
    MFA_SETUP = "mfa_setup"
    MFA_VERIFY = "mfa_verify"


@dataclass(frozen=True)
class LoginResult:
    token: str
    next_step: LoginNextStep


def _now() -> datetime:
    return datetime.now(UTC)


# --- Login --------------------------------------------------------------------------------


def _recent_failures(db: Session, key: str) -> int:
    settings = get_settings()
    window_start = _now() - timedelta(minutes=settings.login_window_minutes)
    last_success = (
        select(func.max(AuthAttempt.attempted_at))
        .where(AuthAttempt.key_hash == key, AuthAttempt.succeeded.is_(True))
        .scalar_subquery()
    )
    return (
        db.scalar(
            select(func.count())
            .select_from(AuthAttempt)
            .where(
                AuthAttempt.key_hash == key,
                AuthAttempt.succeeded.is_(False),
                AuthAttempt.attempted_at >= window_start,
                AuthAttempt.attempted_at > func.coalesce(last_success, window_start),
            )
        )
        or 0
    )


def login(
    db: Session, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> LoginResult:
    settings = get_settings()
    email = email.strip().lower()
    key = crypto.keyed_hash(f"login:{email}")

    if _recent_failures(db, key) >= settings.login_max_failures:
        record_independently("auth.login_throttled", tenant_id=None, actor_user_id=None, ip=ip)
        raise AuthError(AuthErrorCode.TOO_MANY_ATTEMPTS, 429)

    row = db.execute(
        text("SELECT id, password_hash, is_active FROM auth_lookup_user(:email)"),
        {"email": email},
    ).first()
    password_ok = crypto.verify_password(row.password_hash if row else None, password)
    if row is None or not password_ok or not row.is_active:
        with independent_transaction() as fail_db:
            fail_db.add(AuthAttempt(key_hash=key, succeeded=False))
        record_independently(
            "auth.login_failed",
            tenant_id=None,
            actor_user_id=row.id if row else None,
            ip=ip,
        )
        raise AuthError(AuthErrorCode.INVALID_CREDENTIALS, 401)

    user_id: uuid.UUID = row.id
    set_db_context(db, user_id=user_id)
    db.add(AuthAttempt(key_hash=key, succeeded=True))

    tenant_id = db.scalar(
        select(Membership.tenant_id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at)
        .limit(1)
    )
    set_db_context(db, user_id=user_id, tenant_id=tenant_id)

    token = crypto.new_token()
    db.add(
        AuthSession(
            token_hash=crypto.token_hash(token),
            user_id=user_id,
            tenant_id=tenant_id,
            mfa_verified=False,
            expires_at=_now() + timedelta(minutes=settings.pending_mfa_ttl_minutes),
            ip=ip,
            user_agent=(user_agent or "")[:400] or None,
        )
    )
    record(db, "auth.password_accepted", tenant_id=tenant_id, actor_user_id=user_id, ip=ip)

    has_factor = db.scalar(
        select(func.count())
        .select_from(MfaFactor)
        .where(MfaFactor.user_id == user_id, MfaFactor.confirmed_at.is_not(None))
    )
    next_step = LoginNextStep.MFA_VERIFY if has_factor else LoginNextStep.MFA_SETUP
    return LoginResult(token=token, next_step=next_step)


# --- Sessions -----------------------------------------------------------------------------


def resolve_session(db: Session, token: str | None) -> Principal | None:
    """Turn a session cookie into a Principal and set the DB context for the request."""
    if not token:
        return None
    row = db.execute(
        text("SELECT id, user_id, tenant_id, mfa_verified FROM auth_lookup_session(:token_hash)"),
        {"token_hash": crypto.token_hash(token)},
    ).first()
    if row is None:
        return None

    set_db_context(db, user_id=row.user_id, tenant_id=row.tenant_id)
    role: Role | None = None
    tenant_id: uuid.UUID | None = row.tenant_id
    if tenant_id is not None:
        role = db.scalar(
            select(Membership.role).where(
                Membership.tenant_id == tenant_id, Membership.user_id == row.user_id
            )
        )
        if role is None:
            # Membership was removed since login: keep the session but drop firm access.
            tenant_id = None
            set_db_context(db, user_id=row.user_id)
    return Principal(
        session_id=row.id,
        user_id=row.user_id,
        mfa_verified=row.mfa_verified,
        tenant_id=tenant_id,
        role=role,
    )


def logout(db: Session, principal: Principal, *, ip: str | None) -> None:
    db.execute(
        update(AuthSession).where(AuthSession.id == principal.session_id).values(revoked_at=_now())
    )
    record(db, "auth.logout", tenant_id=principal.tenant_id, actor_user_id=principal.user_id, ip=ip)


def _mark_session_verified(db: Session, principal: Principal) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.id == principal.session_id)
        .values(
            mfa_verified=True,
            mfa_failures=0,
            expires_at=_now() + timedelta(hours=get_settings().session_ttl_hours),
        )
    )


def switch_tenant(
    db: Session, principal: Principal, tenant_id: uuid.UUID, *, ip: str | None
) -> None:
    role = db.scalar(
        select(Membership.role).where(
            Membership.tenant_id == tenant_id, Membership.user_id == principal.user_id
        )
    )
    if role is None:
        raise AuthError(AuthErrorCode.NOT_A_MEMBER, 403)
    set_db_context(db, user_id=principal.user_id, tenant_id=tenant_id)
    db.execute(
        update(AuthSession)
        .where(AuthSession.id == principal.session_id)
        .values(tenant_id=tenant_id)
    )
    record(
        db,
        "auth.firm_switched",
        tenant_id=tenant_id,
        actor_user_id=principal.user_id,
        ip=ip,
        details={"from_tenant_id": str(principal.tenant_id) if principal.tenant_id else None},
    )


# --- MFA ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MfaSetup:
    secret: str
    otpauth_uri: str


def _confirmed_factor(db: Session, user_id: uuid.UUID) -> MfaFactor | None:
    return db.scalar(
        select(MfaFactor).where(MfaFactor.user_id == user_id, MfaFactor.confirmed_at.is_not(None))
    )


def start_mfa_setup(db: Session, principal: Principal) -> MfaSetup:
    if _confirmed_factor(db, principal.user_id) is not None:
        raise AuthError(AuthErrorCode.MFA_ALREADY_CONFIGURED, 409)
    db.execute(
        delete(MfaFactor).where(
            MfaFactor.user_id == principal.user_id, MfaFactor.confirmed_at.is_(None)
        )
    )
    secret = pyotp.random_base32()
    db.add(MfaFactor(user_id=principal.user_id, secret_encrypted=crypto.encrypt(secret)))
    email = db.scalar(select(User.email).where(User.id == principal.user_id)) or ""
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)
    return MfaSetup(secret=secret, otpauth_uri=uri)


def _match_totp(factor: MfaFactor, code: str) -> int | None:
    """Return the matched time step, allowing one step of clock drift and rejecting
    a code that was already used (replay)."""
    totp = pyotp.TOTP(crypto.decrypt(factor.secret_encrypted))
    current = int(time.time()) // TOTP_STEP_SECONDS
    for step in (current - 1, current, current + 1):
        if factor.last_used_step is not None and step <= factor.last_used_step:
            continue
        if hmac.compare_digest(totp.at(step * TOTP_STEP_SECONDS), code.strip()):
            return step
    return None


def _register_mfa_failure(principal: Principal, *, ip: str | None) -> None:
    """Count a wrong code in its own transaction (the request will be rolled back), and
    revoke the session after too many failures."""
    max_failures = get_settings().mfa_max_failures
    with independent_transaction(user_id=principal.user_id, tenant_id=principal.tenant_id) as db:
        failures = db.scalar(
            update(AuthSession)
            .where(AuthSession.id == principal.session_id)
            .values(mfa_failures=AuthSession.mfa_failures + 1)
            .returning(AuthSession.mfa_failures)
        )
        if failures is not None and failures >= max_failures:
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == principal.session_id)
                .values(revoked_at=_now())
            )
    record_independently(
        "auth.mfa_failed", tenant_id=principal.tenant_id, actor_user_id=principal.user_id, ip=ip
    )


def _new_recovery_codes(db: Session, user_id: uuid.UUID) -> list[str]:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(RecoveryCode(user_id=user_id, code_hash=crypto.keyed_hash(f"recovery:{code}")))
    return codes


def confirm_mfa_setup(db: Session, principal: Principal, code: str, *, ip: str | None) -> list[str]:
    """Confirm the new authenticator with a first code. Returns one-time recovery codes,
    shown to the user only once."""
    if _confirmed_factor(db, principal.user_id) is not None:
        raise AuthError(AuthErrorCode.MFA_ALREADY_CONFIGURED, 409)
    factor = db.scalar(
        select(MfaFactor).where(
            MfaFactor.user_id == principal.user_id, MfaFactor.confirmed_at.is_(None)
        )
    )
    if factor is None:
        raise AuthError(AuthErrorCode.MFA_SETUP_NOT_STARTED, 409)
    step = _match_totp(factor, code)
    if step is None:
        _register_mfa_failure(principal, ip=ip)
        raise AuthError(AuthErrorCode.INVALID_MFA_CODE, 401)
    factor.confirmed_at = _now()
    factor.last_used_step = step
    codes = _new_recovery_codes(db, principal.user_id)
    _mark_session_verified(db, principal)
    record(
        db,
        "auth.mfa_enrolled",
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        ip=ip,
    )
    return codes


def verify_mfa(
    db: Session,
    principal: Principal,
    *,
    code: str | None,
    recovery_code: str | None,
    ip: str | None,
) -> None:
    factor = _confirmed_factor(db, principal.user_id)
    if factor is None:
        raise AuthError(AuthErrorCode.MFA_SETUP_NOT_STARTED, 409)

    action = "auth.mfa_verified"
    if code:
        step = _match_totp(factor, code)
        if step is None:
            _register_mfa_failure(principal, ip=ip)
            raise AuthError(AuthErrorCode.INVALID_MFA_CODE, 401)
        factor.last_used_step = step
    elif recovery_code:
        used = db.scalar(
            update(RecoveryCode)
            .where(
                RecoveryCode.user_id == principal.user_id,
                RecoveryCode.code_hash == crypto.keyed_hash(f"recovery:{recovery_code.strip()}"),
                RecoveryCode.used_at.is_(None),
            )
            .values(used_at=_now())
            .returning(RecoveryCode.id)
        )
        if used is None:
            _register_mfa_failure(principal, ip=ip)
            raise AuthError(AuthErrorCode.INVALID_MFA_CODE, 401)
        action = "auth.recovery_code_used"
    else:
        raise AuthError(AuthErrorCode.INVALID_MFA_CODE, 401)

    _mark_session_verified(db, principal)
    record(db, action, tenant_id=principal.tenant_id, actor_user_id=principal.user_id, ip=ip)


# --- Read models --------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmSummary:
    id: uuid.UUID
    name: str
    role: Role


def list_my_firms(db: Session, user_id: uuid.UUID) -> list[FirmSummary]:
    rows = db.execute(
        select(Tenant.id, Tenant.name, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user_id)
        .order_by(Tenant.name)
    ).all()
    return [FirmSummary(id=r.id, name=r.name, role=r.role) for r in rows]
