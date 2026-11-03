"""The AI gateway: the single way any part of the system talks to an AI model (brief §4).

For every call it:
- checks the firm's monthly AI budget,
- redacts personal identifiers (if the firm's policy says so) and restores them in the
  answer,
- logs provider, model, purpose, tokens, cost and latency (never prompts or answers),
- turns refusals and truncated answers into explicit errors.
"""

import os
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from legalos.config import get_settings
from legalos.core.db import independent_transaction
from legalos.gateway.models import GatewayCall
from legalos.gateway.pricing import cost_usd
from legalos.gateway.redaction import Redactor
from legalos.gateway.types import AIRequest, AIResponse, DocumentInput, TextPart
from legalos.tenancy.models import Tenant


class Provider(Protocol):
    name: str
    model: str

    def complete(self, request: AIRequest) -> AIResponse: ...


class AIError(Exception):
    """An AI call that must not be retried as is (refused, truncated, over budget)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@lru_cache
def get_provider() -> Provider | None:
    """The configured provider, or None when AI is disabled."""
    settings = get_settings()
    choice = settings.ai_provider
    if choice == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            choice = "anthropic"
        else:
            choice = "demo" if settings.environment != "production" else "disabled"
    if choice == "anthropic":
        from legalos.gateway.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=settings.ai_model)
    if choice == "demo":
        from legalos.gateway.demo_provider import DemoProvider

        return DemoProvider()
    return None


def month_spend(db: Session, tenant_id: uuid.UUID) -> Decimal:
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = db.scalar(
        select(func.coalesce(func.sum(GatewayCall.cost_usd), 0)).where(
            GatewayCall.tenant_id == tenant_id, GatewayCall.created_at >= month_start
        )
    )
    return Decimal(spent or 0)


def call(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    ai_run_id: uuid.UUID | None,
    request: AIRequest,
) -> AIResponse:
    provider = get_provider()
    if provider is None:
        raise AIError("ai_not_configured")
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    if month_spend(db, tenant_id) >= tenant.ai_monthly_budget_usd:
        raise AIError("ai_budget_exceeded")

    redactor = Redactor(enabled=tenant.ai_redaction_enabled)
    outgoing = AIRequest(
        **{
            **request.__dict__,
            "documents": [
                DocumentInput(d.title, [redactor.redact(b) for b in d.blocks])
                for d in request.documents
            ],
        }
    )
    started = time.perf_counter()
    status, response, model = "error", None, provider.model
    try:
        response = provider.complete(outgoing)
        status, model = response.stop, response.model
    finally:
        # Logged in its own transaction: the cost counts even if the workflow fails later.
        with independent_transaction(user_id=user_id, tenant_id=tenant_id) as log_db:
            log_db.add(
                GatewayCall(
                    tenant_id=tenant_id,
                    ai_run_id=ai_run_id,
                    user_id=user_id,
                    purpose=request.purpose,
                    provider=provider.name,
                    model=model,
                    status=status,
                    input_tokens=response.usage.input_tokens if response else 0,
                    output_tokens=response.usage.output_tokens if response else 0,
                    cache_write_tokens=response.usage.cache_write_tokens if response else 0,
                    cache_read_tokens=response.usage.cache_read_tokens if response else 0,
                    cost_usd=cost_usd(model, response.usage) if response else Decimal(0),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    redaction_count=redactor.count,
                    request_id=response.request_id if response else None,
                )
            )
    assert response is not None
    if response.stop == "refused":
        raise AIError("ai_refused")
    if response.stop == "truncated":
        raise AIError("ai_truncated")
    return _restore(response, redactor)


def _restore(response: AIResponse, redactor: Redactor) -> AIResponse:
    for part in response.parts:
        part.text = redactor.restore(part.text)
        for citation in part.citations:
            citation.cited_text = redactor.restore(citation.cited_text)
    if response.json is not None:
        response.json = _restore_json(response.json, redactor)
    return response


def _restore_json(value: Any, redactor: Redactor) -> Any:
    if isinstance(value, str):
        return redactor.restore(value)
    if isinstance(value, list):
        return [_restore_json(v, redactor) for v in value]
    if isinstance(value, dict):
        return {k: _restore_json(v, redactor) for k, v in value.items()}
    return value


__all__ = ["AIError", "AIRequest", "AIResponse", "DocumentInput", "TextPart", "call"]
