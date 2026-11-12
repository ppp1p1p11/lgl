from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from legalos.gateway import service as gateway
from legalos.gateway.demo_provider import DemoProvider
from legalos.maintenance import cleanup
from legalos.tenancy.roles import Role
from tests.conftest import PASSWORD, FakeStorage, login_with_mfa, run_worker, totp_now, upload
from tests.corpus.generator import build_corpus, render_pdf


def test_socio_adds_a_member_who_must_change_password(
    client: TestClient, make_firm, make_member, owner_engine: Engine
) -> None:
    firm = make_firm("Alfa")
    socio = make_member(firm, Role.SOCIO)
    login_with_mfa(client, socio.email)
    r = client.post(
        "/api/firm/members",
        json={
            "name": "Nova Advogada",
            "email": "Nova@Example.com",
            "role": "advogado",
            "oab_number": "654321",
            "oab_uf": "sp",
        },
    )
    assert r.status_code == 201
    temporary = r.json()["temporary_password"]
    assert temporary and len(temporary) >= 12
    members = {m["email"]: m for m in client.get("/api/firm/members").json()}
    assert members["nova@example.com"]["role"] == "advogado"
    assert members["nova@example.com"]["oab"] == "OAB/SP 654321"
    assert (
        client.post(
            "/api/firm/members",
            json={"name": "X Y", "email": "nova@example.com", "role": "estagiario"},
        ).status_code
        == 409
    )

    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": "nova@example.com", "password": temporary})
    assert r.json() == {"next_step": "mfa_setup"}
    secret = client.post("/api/auth/mfa/setup").json()["secret"]
    client.post("/api/auth/mfa/confirm", json={"code": totp_now(secret)})
    me = client.get("/api/auth/me").json()
    assert me["must_change_password"] is True and me["current_firm"]["role"] == "advogado"

    weak = client.post(
        "/api/auth/password", json={"current_password": temporary, "new_password": "curta"}
    )
    assert weak.json() == {"detail": "weak_password"}
    wrong = client.post(
        "/api/auth/password",
        json={"current_password": "errada", "new_password": "uma-senha-bem-longa-1"},
    )
    assert wrong.status_code == 403
    ok = client.post(
        "/api/auth/password",
        json={"current_password": temporary, "new_password": "uma-senha-bem-longa-1"},
    )
    assert ok.status_code == 204
    assert client.get("/api/auth/me").json()["must_change_password"] is False
    with Session(owner_engine) as db:
        actions = db.scalars(text("SELECT action FROM audit_log")).all()
    assert {"firm.member_added", "auth.password_changed", "auth.password_change_failed"} <= set(
        actions
    )


def test_existing_account_joins_without_a_new_password(
    client: TestClient, make_firm, make_member
) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    socio_a = make_member(a, Role.SOCIO)
    person = make_member(b, Role.ADVOGADO)
    login_with_mfa(client, socio_a.email)
    r = client.post(
        "/api/firm/members", json={"name": "Ignorado", "email": person.email, "role": "estagiario"}
    )
    assert r.status_code == 201 and r.json()["temporary_password"] is None
    client.post("/api/auth/logout")
    login_with_mfa(client, person.email)  # their own password still works
    firms = {f["name"]: f["role"] for f in client.get("/api/auth/me").json()["firms"]}
    assert firms == {"Alfa": "estagiario", "Beta": "advogado"}


def test_roles_and_removal_rules(client: TestClient, make_firm, make_member) -> None:
    firm = make_firm("Alfa")
    socio = make_member(firm, Role.SOCIO)
    lawyer = make_member(firm, Role.ADVOGADO)
    login_with_mfa(client, socio.email)
    # The only sócio cannot be demoted or removed, and nobody removes themselves.
    assert client.patch(f"/api/firm/members/{socio.user_id}", json={"role": "advogado"}).json() == {
        "detail": "last_socio"
    }
    assert client.delete(f"/api/firm/members/{socio.user_id}").json() == {
        "detail": "cannot_remove_yourself"
    }
    assert (
        client.patch(f"/api/firm/members/{lawyer.user_id}", json={"role": "socio"}).status_code
        == 204
    )
    assert (
        client.patch(f"/api/firm/members/{socio.user_id}", json={"role": "advogado"}).status_code
        == 204
    )
    # Now an advogado: no longer allowed to manage the team.
    assert client.delete(f"/api/firm/members/{lawyer.user_id}").status_code == 403


def test_only_socios_manage_the_team_and_only_their_own_firm(
    client: TestClient, make_firm, make_member
) -> None:
    a, b = make_firm("Alfa"), make_firm("Beta")
    lawyer_a = make_member(a, Role.ADVOGADO)
    socio_b = make_member(b, Role.SOCIO)
    target_a = make_member(a, Role.ESTAGIARIO)
    login_with_mfa(client, lawyer_a.email)
    assert (
        client.post(
            "/api/firm/members", json={"name": "X Y", "email": "x@example.com", "role": "socio"}
        ).status_code
        == 403
    )
    client.post("/api/auth/logout")
    login_with_mfa(client, socio_b.email)
    assert client.delete(f"/api/firm/members/{target_a.user_id}").status_code == 404
    assert (
        client.patch(f"/api/firm/members/{target_a.user_id}", json={"role": "socio"}).status_code
        == 404
    )


def test_removed_member_loses_access(client: TestClient, make_firm, make_member) -> None:
    firm = make_firm("Alfa")
    socio = make_member(firm, Role.SOCIO)
    intern = make_member(firm, Role.ESTAGIARIO)
    login_with_mfa(client, socio.email)
    assert client.delete(f"/api/firm/members/{intern.user_id}").status_code == 204
    client.post("/api/auth/logout")
    login_with_mfa(client, intern.email)
    assert client.get("/api/matters").json() == {"detail": "no_firm_selected"}


def test_audit_log_shows_actor_names_and_ai_report(
    client: TestClient,
    storage: FakeStorage,
    make_firm,
    make_member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    firm = make_firm("Alfa")
    socio = make_member(firm, Role.SOCIO)
    login_with_mfa(client, socio.email)
    c = client.post("/api/clients", json={"kind": "PF", "name": "Cliente"}).json()
    matter = client.post(
        "/api/matters", json={"client_id": c["id"], "title": "Ação", "area": "civel"}
    ).json()
    ticket = upload(client, storage, matter["id"], render_pdf(build_corpus()[1]))
    run_worker()
    client.post(f"/api/document-versions/{ticket['version_id']}/analysis")
    run_worker()

    events = client.get("/api/audit-log").json()
    assert any(e["actor_name"] == socio.email.split("@")[0] for e in events)
    report = client.get("/api/firm/ai-report").json()
    assert [r["purpose"] for r in report["rows"]] == [
        "classify_document",
        "extract_facts",
        "summarize_document",
    ]
    assert all(r["calls"] == 1 for r in report["rows"])
    assert report["month"] == datetime.now(UTC).strftime("%Y-%m")


def test_maintenance_removes_abandoned_uploads_and_old_sessions(
    client: TestClient, storage: FakeStorage, make_firm, make_member, owner_engine: Engine
) -> None:
    member = make_member(make_firm("Alfa"), Role.ADVOGADO)
    login_with_mfa(client, member.email)
    c = client.post("/api/clients", json={"kind": "PF", "name": "Cliente"}).json()
    matter = client.post(
        "/api/matters", json={"client_id": c["id"], "title": "Ação", "area": "civel"}
    ).json()
    abandoned = client.post(
        f"/api/matters/{matter['id']}/documents",
        json={"filename": "nunca-enviado.pdf", "content_type": "application/pdf", "size_bytes": 10},
    ).json()
    storage.put_via_signed_url(abandoned["upload_url"], b"parcial")
    kept = upload(client, storage, matter["id"], render_pdf(build_corpus()[1]))
    run_worker()

    with Session(owner_engine) as db, db.begin():
        assert cleanup(db)["stale_uploads"] == 0  # too recent to touch
    later = datetime.now(UTC) + timedelta(hours=25)
    with Session(owner_engine) as db, db.begin():
        stats = cleanup(db, now=later)
    assert stats["stale_uploads"] == 1 and stats["empty_documents"] == 1
    documents = client.get(f"/api/matters/{matter['id']}/documents").json()
    assert [d["id"] for d in documents] == [kept["document_id"]]
    assert len(storage.objects) == 1

    with Session(owner_engine) as db, db.begin():
        stats = cleanup(db, now=datetime.now(UTC) + timedelta(days=3))
    assert stats["sessions"] >= 1
    assert client.get("/api/auth/me").status_code == 401
    assert PASSWORD
