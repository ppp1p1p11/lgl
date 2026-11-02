"""Claude via the Anthropic API. The only module allowed to import the `anthropic` SDK."""

import json
from functools import lru_cache
from typing import Any

import anthropic

from legalos.gateway.types import (
    AIRequest,
    AIResponse,
    Citation,
    TextPart,
    TransientProviderError,
    Usage,
)

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side fallback: if the model's safety classifiers decline a request, the API
# retries it on the model Anthropic recommends for that case, in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model

    @staticmethod
    @lru_cache
    def _client() -> anthropic.Anthropic:
        # Reads ANTHROPIC_API_KEY from the environment. Retries 429/5xx twice by default.
        return anthropic.Anthropic()

    def complete(self, request: AIRequest) -> AIResponse:
        content: list[Any] = [
            {
                "type": "document",
                "title": doc.title,
                "source": {
                    "type": "content",
                    "content": [{"type": "text", "text": block} for block in doc.blocks],
                },
                "citations": {"enabled": request.citations},
            }
            for doc in request.documents
        ]
        content.append({"type": "text", "text": request.instruction})
        output_config: Any = {"effort": request.effort}
        if request.output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.output_schema}

        try:
            response = self._client().beta.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": content}],
                output_config=output_config,
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as e:
            raise TransientProviderError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientProviderError(str(e)) from e
            raise

        parts: list[TextPart] = []
        for block in response.content:
            if block.type != "text":
                continue
            citations = [
                Citation(
                    document_index=c.document_index,
                    start_block=c.start_block_index,
                    end_block=c.end_block_index,
                    cited_text=c.cited_text,
                )
                for c in (block.citations or [])
                if c.type == "content_block_location"
            ]
            parts.append(TextPart(text=block.text, citations=citations))

        stop = {"refusal": "refused", "max_tokens": "truncated"}.get(
            response.stop_reason or "", "ok"
        )
        parsed = None
        if request.output_schema is not None and stop == "ok" and parts:
            parsed = json.loads(parts[0].text)
        usage = response.usage
        return AIResponse(
            parts=parts,
            # With a fallback, the model that answered can differ from the one requested.
            model=response.model,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
            ),
            stop=stop,  # type: ignore[arg-type]
            request_id=getattr(response, "_request_id", None),
            json=parsed,
        )
