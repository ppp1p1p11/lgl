import io

import docx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from legalos.corpus.ingest import ingest_demo
from legalos.gateway import service as gateway
from legalos.gateway.demo_provider import DemoProvider
from legalos.gateway.types import AIRequest, AIResponse, Citation, TextPart, Usage
from legalos.tenancy.roles import Role
from tests.conftest import FakeStorage, login_with_mfa, run_worker, upload
from tests.corpus.generator import build_corpus, render_pdf

CONTESTACAO = build_corpus()[1]


class ScriptedDrafter:
    name = "anthropic"
    model = "claude-opus-5-5"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        usage = Usage(input_tokens=800, output_tokens=200)
        if request.purpose == "draft_facts":
            blocks = request.documents[0].blocks
            index = next(i for i, b in enumerate(blocks) if "quitou integralmente" in b)
            return AIResponse(
                [
                    TextPart(
                        "1. O réu quitou a dívida por meio de três transferências.\n",
                        [Citation(0, index, index + 1, "quitou integralmente a dívida")],
                    ),
                    TextPart("2. A autora reconheceu o pagamento por escrito em cartório.\n"),
                    TextPart("3. [PREENCHER: data em que o réu foi citado]\n"),
                ],
                self.model,
                usage,
            )
        index = next(i for i, d in enumerate(request.documents) if "art. 335 (" in d.title)
        return AIResponse(
            [
                TextPart(
                    "A contestação é tempestiva, pois oferecida no prazo legal de quinze dias.\n",
                    [Citation(index, 0, 1, "no prazo de 15 (quinze) dias")],
                ),
            ],
            self.model,
            usage,
        )


@pytest.fixture
def matter_with_document(
    client: TestClient, storage: FakeStorage, make_firm, make_member, owner_engine: Engine
) -> dict:
    with Session(owner_engine) as db, db.begin():
        ingest_demo(db)
        db.execute(text("SELECT 1"))
    firm = make_firm("Alfa")
    member = make_member(firm, Role.ADVOGADO)
    with Session(owner_engine) as db, db.begin():
        db.execute(text("UPDATE users SET oab_number = '123456', oab_uf = 'SP', name = 'Dra. Ana'"))
    login_with_mfa(client, member.email)
    c = client.post(
        "/api/clients",
        json={"kind": "PF", "name": "Patrícia Monteiro", "document_number": "529.982.247-25"},
    ).json()
    matter = client.post(
        "/api/matters",
        json={
            "client_id": c["id"],
            "title": "Ação de cobrança",
            "area": "civel",
            "comarca": "São Paulo",
            "vara": "37ª Vara Cível",
        },
    ).json()
    client.post(
        f"/api/matters/{matter['id']}/parties", json={"name": "Mariana Cavalcanti", "role": "autor"}
    )
    upload(client, storage, matter["id"], render_pdf(CONTESTACAO), title="Contestação")
    run_worker()
    return {"matter": matter, "firm": firm}


def _generate(client: TestClient, matter_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    r = client.post(f"/api/matters/{matter_id}/drafts", json=body)
    assert r.status_code == 202, r.text
    run_worker()
    return client.get(f"/api/drafts/{r.json()['run_id']}").json()


def test_templates_are_listed(client, matter_with_document) -> None:  # type: ignore[no-untyped-def]
    templates = {t["id"]: t for t in client.get("/api/draft-templates").json()}
    assert set(templates) == {
        "peticao_inicial",
        "contestacao",
        "notificacao_extrajudicial",
        "contrato_honorarios",
    }
    assert templates["contestacao"]["uses_legal_corpus"] is True
    assert templates["contrato_honorarios"]["uses_documents"] is False


def test_draft_is_grounded_flagged_and_exportable(
    client, matter_with_document, monkeypatch: pytest.MonkeyPatch, owner_engine: Engine
) -> None:
    provider = ScriptedDrafter()
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    matter = matter_with_document["matter"]
    detail = _generate(
        client,
        matter["id"],
        template_id="contestacao",
        legal_topics="prazo para contestação",
        instructions="Tom objetivo.",
    )
    assert detail["run_status"] == "succeeded"
    output = detail["output"]
    assert (output["kind"], output["status"]) == ("draft", "rascunho")
    content = output["content"]
    assert content["title"] == "Contestação — Ação de cobrança"
    text_all = "\n".join(seg["text"] for s in content["sections"] for seg in s["segments"])
    # Filled from the processo.
    assert "37ª Vara Cível DA COMARCA DE SÃO PAULO" in text_all
    assert "Patrícia Monteiro, já qualificado(a)" in text_all and "Mariana Cavalcanti" in text_all
    assert "Dra. Ana" in text_all and "OAB/SP 123456" in text_all
    # No CNJ number on the matter: visible marker, listed as pending.
    assert "[PREENCHER: número do processo]" in text_all
    assert {"número do processo", "pedidos", "data em que o réu foi citado"} <= set(
        content["pending"]
    )

    segments = {seg["text"].strip(): seg for s in content["sections"] for seg in s["segments"]}
    supported = segments["1. O réu quitou a dívida por meio de três transferências."]
    invented = segments["2. A autora reconheceu o pagamento por escrito em cartório."]
    marker = segments["3. [PREENCHER: data em que o réu foi citado]"]
    assert (supported["unverified"], invented["unverified"], marker["unverified"]) == (
        False,
        True,
        False,
    )
    by_index = {c["item_index"]: c for c in output["citations"]}
    assert by_index[supported["index"]]["page_number"] == 1
    law = segments["A contestação é tempestiva, pois oferecida no prazo legal de quinze dias."]
    assert by_index[law["index"]]["legal_unit_version_id"] is not None
    assert len(output["citations"]) == 2

    # The lawyer's instructions go in the instruction; documents only as attached data.
    facts_request = provider.requests[0]
    assert "Tom objetivo." in facts_request.instruction
    assert "quitou integralmente" not in facts_request.instruction

    # Export while still a draft: clearly marked, with a review report.
    r = client.get(f"/api/ai-outputs/{output['id']}/export.docx")
    assert (
        r.status_code == 200
        and "contestacao-acao-de-cobranca-v1.docx" in r.headers["content-disposition"]
    )
    paragraphs = [p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs]
    assert paragraphs[0] == "RASCUNHO — NÃO APROVADO (versão 1)"
    assert "RELATÓRIO DE CONFERÊNCIA (não protocolar)" in paragraphs
    assert (
        "2. A autora reconheceu o pagamento por escrito em cartório."
        in paragraphs[paragraphs.index("Trechos sem fonte verificada:") :]
    )

    # Edit the facts section: new version, back to draft, its citation dropped.
    facts_index = next(i for i, s in enumerate(content["sections"]) if s["kind"] == "ai_facts")
    r = client.post(
        f"/api/ai-outputs/{output['id']}/sections/{facts_index}",
        json={"base_version_no": 1, "text": "1. O réu pagou a dívida."},
    )
    edited = r.json()
    assert (edited["version_no"], edited["status"], edited["created_by_ai"]) == (
        2,
        "rascunho",
        False,
    )
    assert len(edited["citations"]) == 1 and edited["citations"][0]["legal_unit_version_id"]
    assert "data em que o réu foi citado" not in edited["content"]["pending"]
    stale = client.post(
        f"/api/ai-outputs/{output['id']}/sections/{facts_index}",
        json={"base_version_no": 1, "text": "x"},
    )
    assert stale.status_code == 409

    # Approve version 2: the export carries the approval instead of the draft banner.
    r = client.post(
        f"/api/ai-outputs/{output['id']}/decision", json={"version_no": 2, "decision": "aprovado"}
    )
    assert r.json()["status"] == "aprovado"
    r = client.get(f"/api/ai-outputs/{output['id']}/export.docx")
    paragraphs = [p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs]
    assert not paragraphs[0].startswith("RASCUNHO")
    assert any(p.startswith("Aprovado por Dra. Ana (OAB/SP 123456)") for p in paragraphs)
    r = client.post(
        f"/api/ai-outputs/{output['id']}/sections/{facts_index}",
        json={"base_version_no": 2, "text": "depois de aprovado"},
    )
    assert r.json() == {"detail": "already_decided"}

    listed = client.get(f"/api/matters/{matter['id']}/drafts").json()
    assert [(d["status"], d["version_no"]) for d in listed] == [("aprovado", 2)]
    with Session(owner_engine) as db:
        actions = db.scalars(text("SELECT action FROM audit_log")).all()
    assert actions.count("draft.exported") == 2
    kinds = [e["kind"] for e in client.get(f"/api/matters/{matter['id']}/events").json()]
    assert "minuta_gerada" in kinds


def test_sections_without_sources_become_markers_not_ai_text(
    client, matter_with_document, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedDrafter()
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    matter = matter_with_document["matter"]
    # No legal topic given: the law section is left for the lawyer, with no AI call for it.
    detail = _generate(client, matter["id"], template_id="peticao_inicial")
    assert [r.purpose for r in provider.requests] == ["draft_facts"]
    assert any("fundamentos jurídicos" in p for p in detail["output"]["content"]["pending"])
    # A contract template uses no AI at all.
    provider.requests.clear()
    detail = _generate(client, matter["id"], template_id="contrato_honorarios")
    assert provider.requests == [] and detail["output"]["citations"] == []
    assert "CONTRATADA: Alfa" in detail["output"]["content"]["sections"][1]["segments"][0]["text"]


def test_demo_provider_draft(client, matter_with_document, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    detail = _generate(
        client,
        matter_with_document["matter"]["id"],
        template_id="contestacao",
        legal_topics="prazo para contestação",
    )
    output = detail["output"]
    assert detail["provider"] == "demo" and len(output["citations"]) >= 2
    assert not any(
        seg["unverified"] for s in output["content"]["sections"] for seg in s["segments"]
    )


def test_drafts_are_private_and_validated(
    client, matter_with_document, make_firm, make_member, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gateway, "get_provider", lambda: DemoProvider())
    matter = matter_with_document["matter"]
    r = client.post(f"/api/matters/{matter['id']}/drafts", json={"template_id": "inexistente"})
    assert r.json() == {"detail": "unknown_template"}
    detail = _generate(client, matter["id"], template_id="notificacao_extrajudicial")
    client.post("/api/auth/logout")
    other = make_member(make_firm("Beta"), Role.SOCIO)
    login_with_mfa(client, other.email)
    assert client.get(f"/api/drafts/{detail['run_id']}").status_code == 404
    assert client.get(f"/api/ai-outputs/{detail['output_id']}/export.docx").status_code == 404
    assert client.get(f"/api/matters/{matter['id']}/drafts").status_code == 404
