import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.core.br_ids import cnj_check_digits
from legalos.matters.models import Client, Matter
from legalos.tenancy.roles import Role
from tests.conftest import login_with_mfa

CPF = "529.982.247-25"
CNJ = f"0001234-{cnj_check_digits('0001234', '2024', '8', '26', '0100')}.2024.8.26.0100"


def _client(api: TestClient, **overrides) -> dict:
    body = {"kind": "PF", "name": "Maria Cliente", "document_number": CPF} | overrides
    r = api.post("/api/clients", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _matter(api: TestClient, client_id: str, **overrides) -> dict:
    body = {
        "client_id": client_id,
        "title": "Reclamação trabalhista",
        "area": "trabalhista",
        "cnj_number": CNJ,
        "court": "TRT-2",
    } | overrides
    r = api.post("/api/matters", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_client_identifiers_are_validated_encrypted_and_masked(
    client: TestClient, make_firm, make_member, owner_engine: Engine
) -> None:
    m = make_member(make_firm("Alfa"), Role.ADVOGADO)
    login_with_mfa(client, m.email)

    assert client.post(
        "/api/clients", json={"kind": "PF", "name": "X Y", "document_number": "111.111.111-11"}
    ).json() == {"detail": "invalid_cpf"}
    created = _client(client)
    assert created["document_number"] == "***.982.247-**"
    # Same CPF twice in the same firm is refused.
    assert (
        client.post(
            "/api/clients", json={"kind": "PF", "name": "Outra", "document_number": "52998224725"}
        ).status_code
        == 409
    )
    assert client.get("/api/clients").json()[0]["document_number"] == "***.982.247-**"
    # The detail view shows the full number, and that read is audited.
    assert client.get(f"/api/clients/{created['id']}").json()["document_number"] == CPF
    with Session(owner_engine) as db:
        stored = db.scalar(select(Client.document_number_encrypted))
        actions = list(db.scalars(select(AuditEvent.action)))
    assert stored is not None and b"52998224725" not in stored
    assert "client.identifier_read" in actions


def test_matter_lifecycle(client: TestClient, make_firm, make_member) -> None:
    firm = make_firm("Alfa")
    m = make_member(firm, Role.ADVOGADO)
    colleague = make_member(firm, Role.ESTAGIARIO)
    login_with_mfa(client, m.email)
    c = _client(client)

    bad = client.post(
        "/api/matters",
        json={
            "client_id": c["id"],
            "title": "Processo X",
            "area": "civel",
            "cnj_number": "0001234-00.2024.8.26.0100",
        },
    )
    assert bad.json() == {"detail": "invalid_cnj_number"}

    matter = _matter(client, c["id"], cnj_number=CNJ.replace("-", "").replace(".", ""))
    assert matter["cnj_number"] == CNJ  # stored in canonical format
    assert matter["members"] == [
        {"user_id": str(m.user_id), "name": m.email.split("@")[0], "responsibility": "responsavel"}
    ]
    # Same CNJ number twice in a firm is refused.
    assert (
        client.post(
            "/api/matters",
            json={"client_id": c["id"], "title": "Duplicado", "area": "civel", "cnj_number": CNJ},
        ).status_code
        == 409
    )

    r = client.post(
        f"/api/matters/{matter['id']}/parties",
        json={
            "name": "Empresa Ré Ltda.",
            "role": "reclamada",
            "kind": "PJ",
            "document_number": "11.222.333/0001-81",
        },
    )
    assert r.json()["parties"][0]["document_number"] == "11.***.***/0001-**"

    r = client.put(f"/api/matters/{matter['id']}/members", json={"user_id": str(colleague.user_id)})
    assert len(r.json()["members"]) == 2

    r = client.patch(f"/api/matters/{matter['id']}", json={"status": "suspenso"})
    assert r.json()["status"] == "suspenso"

    kinds = [e["kind"] for e in client.get(f"/api/matters/{matter['id']}/events").json()]
    assert kinds == ["status_alterado", "parte_adicionada", "processo_criado"]

    assert [x["id"] for x in client.get("/api/matters?q=Reclama").json()] == [matter["id"]]
    assert [x["id"] for x in client.get("/api/matters?q=Maria").json()] == [matter["id"]]
    assert client.get("/api/matters?q=nada%25").json() == []


def test_cannot_assign_user_from_another_firm(client: TestClient, make_firm, make_member) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    m = make_member(a)
    outsider = make_member(b)
    login_with_mfa(client, m.email)
    matter = _matter(client, _client(client)["id"])
    r = client.put(f"/api/matters/{matter['id']}/members", json={"user_id": str(outsider.user_id)})
    assert r.json() == {"detail": "not_a_firm_member"}


def test_other_firms_matters_are_invisible(client: TestClient, make_firm, make_member) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    socio_a, socio_b = make_member(a), make_member(b)
    login_with_mfa(client, socio_b.email)
    matter_b = _matter(client, _client(client, name="Cliente de B")["id"])
    client.post("/api/auth/logout")

    login_with_mfa(client, socio_a.email)
    assert client.get("/api/matters").json() == []
    assert client.get("/api/clients").json() == []
    assert client.get(f"/api/matters/{matter_b['id']}").status_code == 404
    assert client.get(f"/api/clients/{matter_b['client_id']}").status_code == 404
    assert client.get(f"/api/matters/{matter_b['id']}/events").status_code == 404
    # Creating a matter for another firm's client fails as if the client did not exist.
    r = client.post(
        "/api/matters",
        json={"client_id": matter_b["client_id"], "title": "Tentativa", "area": "civel"},
    )
    assert r.json() == {"detail": "client_not_found"}


def test_database_refuses_cross_firm_links_even_for_the_owner(
    make_firm, owner_engine: Engine
) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    client_b = uuid.uuid4()
    with Session(owner_engine) as db, db.begin():
        db.add(Client(id=client_b, tenant_id=b, kind="PF", name="Cliente B"))
    try:
        with Session(owner_engine) as db, db.begin():
            db.add(Matter(tenant_id=a, client_id=client_b, title="Misturado", area="civel"))
        raise AssertionError("expected a foreign key violation")
    except IntegrityError as e:
        assert "foreign key" in str(e)


def test_timeline_is_append_only_for_the_app(make_firm, owner_engine: Engine) -> None:
    from tests.conftest import app_db

    a = make_firm("Alfa")
    with app_db(tenant_id=a) as db:
        privileges = db.execute(
            text(
                "SELECT has_table_privilege(current_user, 'matter_events', 'UPDATE'),"
                " has_table_privilege(current_user, 'matter_events', 'DELETE')"
            )
        ).one()
    assert tuple(privileges) == (False, False)
