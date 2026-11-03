"""The AI gateway: redaction, budget, cost log, refusals, and that it is the only way out."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from legalos.gateway import service as gateway
from legalos.gateway.models import GatewayCall
from legalos.gateway.pricing import cost_usd
from legalos.gateway.redaction import Redactor
from legalos.gateway.types import (
    AIRequest,
    AIResponse,
    Citation,
    DocumentInput,
    TextPart,
    Usage,
)
from tests.conftest import app_db

DOC = (
    "Maria Silva, CPF 529.982.247-25, RG 12.345.678-9, e-mail maria@exemplo.com.br, "
    "telefone (11) 98765-4321, CEP 01310-100, representada por advogado OAB/SP 123.456, "
    "contra Empresa X, CNPJ 11.222.333/0001-81 e 12.ABC.345/01DE-35, no processo "
    "0001234-56.2024.8.26.0100, valor R$ 25.216,71, em 05/07/2025."
)


class ScriptedProvider:
    name = "scripted"
    model = "claude-opus-5-5"

    def __init__(self, response: AIResponse) -> None:
        self.response = response
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return self.response


def _request() -> AIRequest:
    return AIRequest(
        purpose="test", system="sys", instruction="instr", documents=[DocumentInput("Doc", [DOC])]
    )


def test_redaction_round_trip() -> None:
    redactor = Redactor()
    redacted = redactor.redact(DOC)
    for secret in (
        "529.982.247-25",
        "12.345.678-9",
        "maria@exemplo",
        "98765-4321",
        "01310-100",
        "123.456",
        "11.222.333/0001-81",
        "12.ABC.345/01DE-35",
    ):
        assert secret not in redacted
    # Work-relevant data stays: names, case number, amounts, dates.
    for kept in ("Maria Silva", "0001234-56.2024.8.26.0100", "R$ 25.216,71", "05/07/2025"):
        assert kept in redacted
    assert redactor.count == 8
    assert redactor.redact("de novo 529.982.247-25") == "de novo [CPF_1]"
    assert redactor.restore(redacted) == DOC
    assert Redactor(enabled=False).redact(DOC) == DOC


def test_cost() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000)
    assert cost_usd("claude-opus-5-5", usage) == Decimal("6.20")
    # Unknown models are billed at the most expensive known rate.
    assert cost_usd("model-from-the-future", usage) >= cost_usd("claude-opus-5-5", usage)


@pytest.fixture
def firm(make_firm, make_member):  # type: ignore[no-untyped-def]
    firm_id = make_firm("Alfa")
    return firm_id, make_member(firm_id).user_id


def test_call_redacts_restores_and_logs_without_prompts(
    firm, monkeypatch: pytest.MonkeyPatch, owner_engine: Engine
) -> None:
    tenant_id, user_id = firm
    provider = ScriptedProvider(
        AIResponse(
            parts=[
                TextPart("A autora [CPF_1] ...", [Citation(0, 0, 1, "Maria Silva, CPF [CPF_1]")])
            ],
            model="claude-opus-5-5",
            usage=Usage(input_tokens=1000, output_tokens=200),
            json={"facts": [{"quote": "CPF [CPF_1]"}]},
            request_id="req_123",
        )
    )
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    with app_db(tenant_id=tenant_id, user_id=user_id) as db:
        response = gateway.call(
            db, tenant_id=tenant_id, user_id=user_id, ai_run_id=None, request=_request()
        )

    sent = provider.requests[0].documents[0].blocks[0]
    assert "529.982.247-25" not in sent and "[CPF_1]" in sent
    assert response.parts[0].text == "A autora 529.982.247-25 ..."
    assert response.parts[0].citations[0].cited_text == "Maria Silva, CPF 529.982.247-25"
    assert response.json == {"facts": [{"quote": "CPF 529.982.247-25"}]}

    with Session(owner_engine) as db:
        logged = db.scalars(select(GatewayCall)).one()
        columns = (
            db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'gateway_calls'"
                )
            )
            .scalars()
            .all()
        )
    assert (logged.purpose, logged.status, logged.redaction_count) == ("test", "ok", 8)
    assert logged.cost_usd == Decimal("0.008")  # 1000 * $4/M + 200 * $20/M
    assert logged.request_id == "req_123"
    assert not {"prompt", "response", "content", "text"} & set(columns)


def test_redaction_can_be_disabled_per_firm(firm, monkeypatch, owner_engine) -> None:  # type: ignore[no-untyped-def]
    tenant_id, user_id = firm
    with Session(owner_engine) as db, db.begin():
        db.execute(text("UPDATE tenants SET ai_redaction_enabled = false"))
    provider = ScriptedProvider(AIResponse(parts=[TextPart("ok")], model="m", usage=Usage()))
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    with app_db(tenant_id=tenant_id, user_id=user_id) as db:
        gateway.call(db, tenant_id=tenant_id, user_id=user_id, ai_run_id=None, request=_request())
    assert "529.982.247-25" in provider.requests[0].documents[0].blocks[0]


def test_budget_blocks_calls(firm, monkeypatch, owner_engine) -> None:  # type: ignore[no-untyped-def]
    tenant_id, user_id = firm
    provider = ScriptedProvider(
        AIResponse(
            parts=[TextPart("ok")], model="claude-opus-5-5", usage=Usage(input_tokens=1_000_000)
        )
    )  # $4
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    with Session(owner_engine) as db, db.begin():
        db.execute(text("UPDATE tenants SET ai_monthly_budget_usd = 3"))
    with app_db(tenant_id=tenant_id, user_id=user_id) as db:
        gateway.call(db, tenant_id=tenant_id, user_id=user_id, ai_run_id=None, request=_request())
    with pytest.raises(gateway.AIError) as err, app_db(tenant_id=tenant_id, user_id=user_id) as db:
        gateway.call(db, tenant_id=tenant_id, user_id=user_id, ai_run_id=None, request=_request())
    assert err.value.code == "ai_budget_exceeded"
    assert len(provider.requests) == 1


def test_refusal_is_an_error_but_still_logged(firm, monkeypatch, owner_engine) -> None:  # type: ignore[no-untyped-def]
    tenant_id, user_id = firm
    provider = ScriptedProvider(
        AIResponse(parts=[], model="claude-opus-5-5", usage=Usage(input_tokens=10), stop="refused")
    )
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)
    with pytest.raises(gateway.AIError) as err, app_db(tenant_id=tenant_id, user_id=user_id) as db:
        gateway.call(db, tenant_id=tenant_id, user_id=user_id, ai_run_id=None, request=_request())
    assert err.value.code == "ai_refused"
    with Session(owner_engine) as db:
        assert db.scalar(select(GatewayCall.status)) == "refused"


def test_only_the_gateway_talks_to_ai_providers() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "legalos"
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if re.search(r"^\s*(import anthropic|from anthropic)", path.read_text(), re.MULTILINE)
        and path.relative_to(src).as_posix() != "gateway/anthropic_provider.py"
    ]
    assert offenders == []


def test_auto_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    from legalos.config import get_settings

    settings = get_settings()
    gateway.get_provider.cache_clear()
    try:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert gateway.get_provider().name == "demo"  # type: ignore[union-attr]
        gateway.get_provider.cache_clear()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert gateway.get_provider().name == "anthropic"  # type: ignore[union-attr]
        gateway.get_provider.cache_clear()
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        monkeypatch.setattr(settings, "environment", "production")
        assert gateway.get_provider() is None
    finally:
        gateway.get_provider.cache_clear()
