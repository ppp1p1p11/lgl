"""Provider-neutral request and response shapes used by the AI gateway."""

from dataclasses import dataclass, field
from typing import Any, Literal

Effort = Literal["low", "medium", "high", "xhigh", "max"]
StopStatus = Literal["ok", "refused", "truncated"]


@dataclass
class DocumentInput:
    """A document passed as data, never as instructions. Each block is one chunk."""

    title: str
    blocks: list[str]


@dataclass
class AIRequest:
    purpose: str
    system: str
    instruction: str
    documents: list[DocumentInput]
    effort: Effort = "medium"
    max_tokens: int = 16000
    # JSON Schema for a structured answer (incompatible with citations).
    output_schema: dict[str, Any] | None = None
    # Ask the provider to cite exact passages of the documents.
    citations: bool = False


@dataclass
class Citation:
    document_index: int
    start_block: int
    end_block: int  # exclusive
    cited_text: str


@dataclass
class TextPart:
    text: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class AIResponse:
    parts: list[TextPart]
    model: str
    usage: Usage
    stop: StopStatus = "ok"
    request_id: str | None = None
    json: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.parts)


class TransientProviderError(Exception):
    """The provider is temporarily unavailable (rate limit, overload, network): retry later."""
