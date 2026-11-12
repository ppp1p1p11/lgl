from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from legalos.tenancy.roles import Role
from tests.conftest import login_with_mfa

BODY = {
    "title": "Contestação",
    "rule_set": "cpc",
    "preset_id": "cpc_contestacao",
    "trigger_kind": "ciencia",
    "trigger_date": "2026-04-16",
    "days": 3,
}


def _setup(client: TestClient, make_firm, make_member, role=Role.ADVOGADO):  # type: ignore[no-untyped-def]
    firm = make_firm("Alfa")
    member = make_member(firm, role)
    login_with_mfa(client, member.email)
    c = client.post("/api/clients", json={"kind": "PF", "name": "Cliente"}).json()
    matter = client.post(
        "/api/matters", json={"client_id": c["id"], "title": "Ação X", "area": "civel"}
    ).json()
    return firm, member, matter


def test_rules_catalog_and_preview(client: TestClient, make_firm, make_member) -> None:
    _setup(client, make_firm, make_member)
    rules = client.get("/api/deadline-rules").json()
    assert {r["id"] for r in rules["rule_sets"]} == {"cpc", "clt", "jec"}
    assert any(p["id"] == "cpc_contestacao" and p["days"] == 15 for p in rules["presets"])
    # National holiday (Tiradentes, seeded by the migration) is skipped: 17, 20, [21], 22.
    preview = client.post("/api/deadline-preview", json=BODY).json()
    assert preview["proposed_date"] == "2026-04-22"
    assert any("Tiradentes" in s["detail"] for s in preview["steps"])


def test_proposal_needs_a_lawyer_to_confirm(
    client: TestClient, make_firm, make_member, owner_engine: Engine
) -> None:
    firm, _intern, matter = _setup(client, make_firm, make_member, Role.ESTAGIARIO)
    r = client.post(f"/api/matters/{matter['id']}/deadline-proposals", json=BODY)
    assert r.status_code == 201
    proposal = r.json()
    assert (proposal["status"], proposal["proposed_date"]) == ("proposto", "2026-04-22")
    assert client.get(f"/api/matters/{matter['id']}/tasks").json() == []  # nothing final yet

    decision_url = f"/api/deadline-proposals/{proposal['id']}/decision"
    assert client.post(decision_url, json={"decision": "confirmado"}).status_code == 403

    client.post("/api/auth/logout")
    lawyer = make_member(firm, Role.ADVOGADO)
    login_with_mfa(client, lawyer.email)
    # A different date needs a justification.
    r = client.post(decision_url, json={"decision": "confirmado", "confirmed_date": "2026-04-20"})
    assert r.json() == {"detail": "note_required_for_different_date"}
    r = client.post(
        decision_url,
        json={
            "decision": "confirmado",
            "confirmed_date": "2026-04-20",
            "note": "Feriado municipal não cadastrado.",
        },
    )
    confirmed = r.json()
    assert (confirmed["status"], confirmed["confirmed_date"]) == ("confirmado", "2026-04-20")
    assert confirmed["decided_by_name"]
    assert client.post(decision_url, json={"decision": "rejeitado"}).json() == {
        "detail": "already_decided"
    }

    [task] = client.get(f"/api/matters/{matter['id']}/tasks").json()
    assert (task["title"], task["due_date"], task["origin"]) == (
        "Prazo: Contestação",
        "2026-04-20",
        "prazo",
    )
    kinds = [e["kind"] for e in client.get(f"/api/matters/{matter['id']}/events").json()]
    assert "prazo_proposto" in kinds and "prazo_confirmado" in kinds
    with Session(owner_engine) as db:
        actions = db.scalars(text("SELECT action FROM audit_log")).all()
    assert "deadline.confirmado" in actions


def test_rejected_proposal_creates_no_task(client: TestClient, make_firm, make_member) -> None:
    _firm, _m, matter = _setup(client, make_firm, make_member)
    proposal = client.post(f"/api/matters/{matter['id']}/deadline-proposals", json=BODY).json()
    r = client.post(
        f"/api/deadline-proposals/{proposal['id']}/decision",
        json={"decision": "rejeitado", "note": "Intimação anulada."},
    )
    assert r.json()["status"] == "rejeitado" and r.json()["confirmed_date"] is None
    assert client.get(f"/api/matters/{matter['id']}/tasks").json() == []


def test_firm_holidays_change_only_that_firms_calculation(
    client: TestClient, make_firm, make_member
) -> None:
    _firm, _m, _matter = _setup(client, make_firm, make_member)
    national = client.get("/api/holidays", params={"year": 2026}).json()
    assert len(national) == 9 and all(h["system"] for h in national)
    tiradentes = next(h for h in national if h["name"] == "Tiradentes")
    assert client.delete(f"/api/holidays/{tiradentes['id']}").status_code == 404

    suggestions = client.get("/api/holidays/suggestions", params={"year": 2026}).json()
    assert [s["day"] for s in suggestions] == [
        "2026-02-16",
        "2026-02-17",
        "2026-04-03",
        "2026-06-04",
    ]
    r = client.post(
        "/api/holidays",
        json={
            "day": "2026-04-20",
            "name": "Ponte de Tiradentes",
            "kind": "suspensao_expediente",
            "scope": "TJSP",
        },
    )
    assert r.status_code == 201
    assert client.post("/api/holidays", json={"day": "2026-04-20", "name": "x2"}).status_code == 409
    # 17 (1), [20 local], [21 national], 22 (2), 23 (3).
    assert client.post("/api/deadline-preview", json=BODY).json()["proposed_date"] == "2026-04-23"

    client.post("/api/auth/logout")
    other = make_member(make_firm("Beta"), Role.SOCIO)
    login_with_mfa(client, other.email)
    assert client.post("/api/deadline-preview", json=BODY).json()["proposed_date"] == "2026-04-22"
    assert len(client.get("/api/holidays", params={"year": 2026}).json()) == 9
    assert client.delete(f"/api/holidays/{r.json()['id']}").status_code == 404


def test_tasks(client: TestClient, make_firm, make_member) -> None:
    _firm, member, matter = _setup(client, make_firm, make_member)
    outsider = make_member(make_firm("Beta"))
    r = client.post(
        f"/api/matters/{matter['id']}/tasks",
        json={
            "title": "Ligar para o cliente",
            "due_date": "2026-05-10",
            "assignee_user_id": str(member.user_id),
        },
    )
    task = r.json()
    assert r.status_code == 201 and task["assignee_name"]
    r = client.post(
        f"/api/matters/{matter['id']}/tasks",
        json={"title": "Tarefa", "assignee_user_id": str(outsider.user_id)},
    )
    assert r.json() == {"detail": "not_a_firm_member"}

    assert [t["id"] for t in client.get("/api/tasks").json()] == [task["id"]]
    assert [t["id"] for t in client.get("/api/tasks", params={"mine": True}).json()] == [task["id"]]
    r = client.patch(f"/api/tasks/{task['id']}", json={"status": "concluida"})
    assert r.json()["status"] == "concluida"
    assert client.get("/api/tasks").json() == []
    assert len(client.get("/api/tasks", params={"status": "concluida"}).json()) == 1


def test_other_firm_cannot_touch_deadlines_or_tasks(
    client: TestClient, make_firm, make_member
) -> None:
    _firm, _m, matter = _setup(client, make_firm, make_member)
    proposal = client.post(f"/api/matters/{matter['id']}/deadline-proposals", json=BODY).json()
    task = client.post(f"/api/matters/{matter['id']}/tasks", json={"title": "Tarefa A"}).json()
    client.post("/api/auth/logout")
    other = make_member(make_firm("Beta"), Role.SOCIO)
    login_with_mfa(client, other.email)
    assert client.get(f"/api/matters/{matter['id']}/deadline-proposals").status_code == 404
    assert (
        client.post(
            f"/api/deadline-proposals/{proposal['id']}/decision", json={"decision": "confirmado"}
        ).status_code
        == 404
    )
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "concluida"}).status_code == 404
    assert client.get("/api/tasks").json() == []


def test_manual_movement_on_timeline(client: TestClient, make_firm, make_member) -> None:
    _firm, _m, matter = _setup(client, make_firm, make_member)
    r = client.post(
        f"/api/matters/{matter['id']}/events",
        json={
            "kind": "intimacao",
            "summary": "Intimação para contestar",
            "occurred_on": "2026-04-16",
        },
    )
    assert r.status_code == 201 and r.json()["occurred_at"].startswith("2026-04-16")
    events = client.get(f"/api/matters/{matter['id']}/events").json()
    assert any(e["kind"] == "intimacao" for e in events)
