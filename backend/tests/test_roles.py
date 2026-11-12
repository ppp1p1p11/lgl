import pytest
from fastapi.testclient import TestClient

from legalos.tenancy.roles import ROLE_PERMISSIONS, Permission, Role, has_permission
from tests.conftest import login_with_mfa


def test_socio_has_every_permission() -> None:
    assert ROLE_PERMISSIONS[Role.SOCIO] == frozenset(Permission)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.ADVOGADO, Permission.APPROVE_AI_OUTPUTS, True),
        (Role.ADVOGADO, Permission.CONFIRM_DEADLINES, True),
        (Role.ADVOGADO, Permission.VIEW_AUDIT_LOG, False),
        (Role.ADVOGADO, Permission.MANAGE_MEMBERS, False),
        (Role.ESTAGIARIO, Permission.DRAFT_AI_OUTPUTS, True),
        (Role.ESTAGIARIO, Permission.APPROVE_AI_OUTPUTS, False),
        (Role.ESTAGIARIO, Permission.CONFIRM_DEADLINES, False),
        (Role.ADMINISTRATIVO, Permission.MANAGE_DOCUMENTS, True),
        (Role.ADMINISTRATIVO, Permission.VIEW_AI_OUTPUTS, False),
        (Role.ADMINISTRATIVO, Permission.APPROVE_AI_OUTPUTS, False),
    ],
)
def test_permission_matrix(role: Role, permission: Permission, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed


@pytest.mark.parametrize(
    ("role", "status"),
    [(Role.SOCIO, 200), (Role.ADVOGADO, 403), (Role.ESTAGIARIO, 403), (Role.ADMINISTRATIVO, 403)],
)
def test_audit_log_endpoint_is_socio_only(
    client: TestClient, make_firm, make_member, role, status
) -> None:
    m = make_member(make_firm("Alfa"), role)
    login_with_mfa(client, m.email)
    assert client.get("/api/audit-log").status_code == status


def test_reading_audit_log_is_itself_audited(client: TestClient, make_firm, make_member) -> None:
    m = make_member(make_firm("Alfa"))
    login_with_mfa(client, m.email)
    client.get("/api/audit-log")
    actions = [e["action"] for e in client.get("/api/audit-log").json()]
    assert actions[0] == "audit_log.read"
