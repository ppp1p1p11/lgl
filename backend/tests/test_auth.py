import time

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.auth.models import AuthSession
from legalos.tenancy.roles import Role
from tests.conftest import PASSWORD, login_with_mfa, totp_now


def _actions(owner_engine: Engine) -> list[str]:
    with Session(owner_engine) as db:
        return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.id)))


def test_full_login_with_mfa_enrollment(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    firm = make_firm("Alfa")
    m = make_member(firm, Role.ADVOGADO)

    r = client.post("/api/auth/login", json={"email": m.email.upper(), "password": PASSWORD})
    assert r.status_code == 200
    assert r.json() == {"next_step": "mfa_setup"}

    # Password alone gives no access to firm data.
    assert client.get("/api/firm/members").json() == {"detail": "mfa_required"}
    me = client.get("/api/auth/me").json()
    assert me["mfa_verified"] is False and me["firms"] == [] and me["current_firm"] is None

    setup = client.post("/api/auth/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    r = client.post("/api/auth/mfa/confirm", json={"code": totp_now(setup["secret"])})
    assert r.status_code == 200
    assert len(r.json()["recovery_codes"]) == 10

    me = client.get("/api/auth/me").json()
    assert me["mfa_verified"] is True
    assert me["current_firm"]["id"] == str(firm) and me["current_firm"]["role"] == "advogado"
    assert "approve_ai_outputs" in me["permissions"]
    assert client.get("/api/firm/members").status_code == 200
    assert _actions(owner_engine) == ["auth.password_accepted", "auth.mfa_enrolled"]


def test_second_login_requires_existing_totp(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    secret = login_with_mfa(client, m.email)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    assert r.json() == {"next_step": "mfa_verify"}
    # Setting up a second authenticator over a pending session is not allowed.
    assert client.post("/api/auth/mfa/setup").status_code == 409
    # The code used at enrollment cannot be replayed; the next time step works.
    later = pyotp.TOTP(secret).at(time.time() + 30)
    assert client.post("/api/auth/mfa/verify", json={"code": later}).status_code == 204
    assert client.get("/api/firm/members").status_code == 200


def test_totp_code_cannot_be_replayed(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    secret = client.post("/api/auth/mfa/setup").json()["secret"]
    used_code = totp_now(secret)
    assert client.post("/api/auth/mfa/confirm", json={"code": used_code}).status_code == 200
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    assert client.post("/api/auth/mfa/verify", json={"code": used_code}).status_code == 401


def test_wrong_password_is_rejected_and_audited(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    r = client.post("/api/auth/login", json={"email": m.email, "password": "errada"})
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}
    r = client.post("/api/auth/login", json={"email": "ninguem@example.com", "password": "x"})
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}
    assert "legalos_session" not in client.cookies
    assert _actions(owner_engine) == ["auth.login_failed", "auth.login_failed"]
    with Session(owner_engine) as db:
        # Throttling records never store the email itself.
        keys = db.scalars(text("SELECT key_hash FROM auth_attempts")).all()
    assert keys and all(m.email not in k for k in keys)


def test_login_is_throttled_after_repeated_failures(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    for _ in range(5):
        client.post("/api/auth/login", json={"email": m.email, "password": "errada"})
    r = client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    assert r.status_code == 429 and r.json() == {"detail": "too_many_attempts"}
    assert _actions(owner_engine)[-1] == "auth.login_throttled"


def test_session_revoked_after_too_many_mfa_failures(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    login_with_mfa(client, m.email)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    for _ in range(5):
        r = client.post("/api/auth/mfa/verify", json={"code": "000000"})
        assert r.status_code == 401
    assert client.get("/api/auth/me").json() == {"detail": "not_authenticated"}
    assert _actions(owner_engine).count("auth.mfa_failed") == 5


def test_recovery_code_works_once(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    secret = client.post("/api/auth/mfa/setup").json()["secret"]
    codes = client.post("/api/auth/mfa/confirm", json={"code": totp_now(secret)}).json()[
        "recovery_codes"
    ]
    for expected in (204, 401):
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
        r = client.post("/api/auth/mfa/verify", json={"recovery_code": codes[0]})
        assert r.status_code == expected


def test_session_cookie_flags(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    r = client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie


def test_sessions_are_stored_hashed(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    token = client.cookies["legalos_session"]
    with Session(owner_engine) as db:
        stored = db.scalars(select(AuthSession.token_hash)).all()
    assert len(stored) == 1 and token.encode() not in stored[0]


def test_pending_mfa_session_expires(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    with Session(owner_engine) as db, db.begin():
        db.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    assert client.get("/api/auth/me").status_code == 401


def test_cross_site_post_is_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403 and r.json() == {"detail": "origin_not_allowed"}


def test_switch_between_own_firms(client: TestClient, make_firm, make_member, owner_engine) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    m = make_member(a, Role.SOCIO)
    make_member(b, Role.ESTAGIARIO, email=m.email)
    login_with_mfa(client, m.email)
    me = client.get("/api/auth/me").json()
    assert {f["id"] for f in me["firms"]} == {str(a), str(b)}

    assert client.post("/api/auth/switch-firm", json={"tenant_id": str(b)}).status_code == 204
    me = client.get("/api/auth/me").json()
    assert me["current_firm"]["id"] == str(b) and me["current_firm"]["role"] == "estagiario"
    # Role follows the firm: an estagiário cannot read the audit log.
    assert client.get("/api/audit-log").status_code == 403


def test_security_headers(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


def test_removed_membership_loses_firm_access(
    client: TestClient, make_firm, make_member, owner_engine
) -> None:
    m = make_member(make_firm("Alfa"))
    login_with_mfa(client, m.email)
    with Session(owner_engine) as db, db.begin():
        db.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": m.user_id})
    assert client.get("/api/firm/members").json() == {"detail": "no_firm_selected"}


def test_mfa_verify_requires_a_code(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    login_with_mfa(client, m.email)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": m.email, "password": PASSWORD})
    assert client.post("/api/auth/mfa/verify", json={}).status_code == 401
