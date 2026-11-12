import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from legalos.corpus.ingest import ingest_demo
from legalos.corpus.models import LegalUnitVersion
from legalos.gateway import service as gateway
from legalos.gateway.demo_provider import DemoProvider
from legalos.gateway.types import AIRequest, AIResponse, Citation, TextPart, Usage
from legalos.tenancy.roles import Role
from tests.conftest import login_with_mfa, run_worker


class ScriptedResearch:
    name = "anthropic"
    model = "claude-opus-5-5"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        index = next(i for i, d in enumerate(request.documents) if "art. 335 (" in d.title)
        return AIResponse(
            [
                TextPart("Resposta\n"),
                TextPart(
                    "O réu pode contestar em 15 dias.",
                    [Citation(index, 0, 1, "no prazo de 15 (quinze) dias")],
                ),
                # Cites a real source, but with words that are not in it.
                TextPart(
                    "O prazo é contado em dobro para qualquer réu.",
                    [Citation(index, 0, 1, "prazo em dobro para qualquer réu")],
                ),
                # Cites a source that was never attached.
                TextPart(
                    "A jurisprudência é pacífica nesse sentido há décadas.",
                    [Citation(99, 0, 1, "jurisprudência pacífica")],
                ),
                TextPart("\nFatos faltantes\n"),
                TextPart("As fontes não tratam de prazos em juizados especiais."),
            ],
            self.model,
            Usage(input_tokens=500, output_tokens=100),
        )


@pytest.fixture
def firm_user(client: TestClient, make_firm, make_member, owner_engine: Engine):  # type: ignore[no-untyped-def]
    with Session(owner_engine) as db, db.begin():
        ingest_demo(db)
    firm = make_firm("Alfa")
    member = make_member(firm, Role.ADVOGADO)
    login_with_mfa(client, member.email)
    return firm, member


def _ask(client: TestClient, question: str, **extra) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/research", json={"question": question, **extra})
    assert r.status_code == 202, r.text
    run_worker()
    return client.get(f"/api/research/{r.json()['run_id']}").json()


def test_research_answer_keeps_only_verified_citations(
    client, firm_user, monkeypatch: pytest.MonkeyPatch, owner_engine: Engine
) -> None:
    provider = ScriptedResearch()
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    detail = _ask(client, "Qual o prazo para contestação?")

    assert detail["status"] == "succeeded"
    output = detail["output"]
    assert (output["kind"], output["status"]) == ("research_answer", "rascunho")
    by_text = {s["text"].strip(): s for s in output["content"]["segments"]}
    assert by_text["O réu pode contestar em 15 dias."]["unverified"] is False
    assert by_text["O prazo é contado em dobro para qualquer réu."]["unverified"] is True
    assert by_text["A jurisprudência é pacífica nesse sentido há décadas."]["unverified"] is True
    assert by_text["As fontes não tratam de prazos em juizados especiais."]["kind"] == "gap"

    [citation] = output["citations"]
    assert citation["verification"] == "verificado"
    with Session(owner_engine) as db:
        unit_text = db.scalar(
            select(LegalUnitVersion.text).where(
                LegalUnitVersion.id == citation["legal_unit_version_id"]
            )
        )
    assert unit_text[citation["char_start"] : citation["char_end"]] == citation["quoted_text"]

    sources = output["content"]["sources"]
    assert sources[0]["label"] == "art. 335"
    assert all(s["review_status"] == "demonstracao_nao_conferida" for s in sources)
    # The model only ever saw indexed passages, each labelled with type and status.
    sent = provider.requests[0]
    assert "Never cite from memory" in sent.system
    assert all(d.title.startswith("Legislação — CPC, art.") for d in sent.documents)
    assert all("vigente" in d.title for d in sent.documents)


def test_no_sources_means_no_ai_call_and_no_answer(
    client, firm_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedResearch()
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    detail = _ask(client, "Xyzzy qwerty?")
    assert detail["status"] == "succeeded" and provider.requests == []
    segments = detail["output"]["content"]["segments"]
    assert "não contém dispositivos" in segments[1]["text"]
    assert detail["output"]["citations"] == []


def test_demo_provider_and_review_flow(client, firm_user, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    _firm, _member = firm_user
    c = client.post("/api/clients", json={"kind": "PF", "name": "Cliente"}).json()
    matter = client.post(
        "/api/matters", json={"client_id": c["id"], "title": "Ação", "area": "civel"}
    ).json()
    detail = _ask(client, "Como se contam os prazos em dias úteis?", matter_id=matter["id"])
    output = detail["output"]
    assert detail["provider"] == "demo" and output["citations"]
    assert {c["verification"] for c in output["citations"]} == {"verificado"}

    listed = client.get("/api/research", params={"matter_id": matter["id"]}).json()
    assert [r["run_id"] for r in listed] == [detail["run_id"]]
    r = client.post(
        f"/api/ai-outputs/{output['id']}/decision", json={"version_no": 1, "decision": "aprovado"}
    )
    assert r.json()["status"] == "aprovado"
    kinds = [e["kind"] for e in client.get(f"/api/matters/{matter['id']}/events").json()]
    assert "pesquisa_concluida" in kinds and "ia_aprovado" in kinds
    assert client.get(f"/api/research/{detail['run_id']}").json()["output_status"] == "aprovado"


def test_research_is_private_to_the_firm(
    client, firm_user, make_firm, make_member, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    detail = _ask(client, "Qual o prazo para contestação?")
    client.post("/api/auth/logout")
    other = make_member(make_firm("Beta"), Role.SOCIO)
    login_with_mfa(client, other.email)
    assert client.get(f"/api/research/{detail['run_id']}").status_code == 404
    assert client.get("/api/research").json() == []
    # The corpus itself is shared.
    assert client.get("/api/corpus/search", params={"q": "contestação"}).json()[0]["label"] == (
        "art. 335"
    )
    docs = client.get("/api/corpus/documents").json()
    assert docs[0]["short_name"] == "CPC" and docs[0]["units"] == 24


def test_research_for_unknown_matter(client, firm_user, monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid

    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    r = client.post(
        "/api/research", json={"question": "Qual o prazo?", "matter_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404
