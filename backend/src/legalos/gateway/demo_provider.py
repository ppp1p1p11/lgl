"""Simulated AI for demonstrations and local trials without an API key.

It follows the same contract as the real provider (structured answers, citations to
exact passages) using simple rules, so the whole review flow can be tried end to end.
Its results are labelled "IA simulada" in the UI and must never be mistaken for analysis.
"""

import re
from typing import Any

from legalos.gateway.types import AIRequest, AIResponse, Citation, TextPart, Usage

_CLASS_KEYWORDS = [
    ("sentenca", ("SENTENÇA", "JULGO PROCEDENTE", "JULGO IMPROCEDENTE")),
    ("contestacao", ("CONTESTAÇÃO",)),
    ("embargos", ("EMBARGOS",)),
    ("peticao_inicial", ("RECLAMAÇÃO TRABALHISTA", "PETIÇÃO INICIAL", "vem propor")),
    ("contrato", ("CONTRATO", "CLÁUSULA")),
    ("procuracao", ("PROCURAÇÃO",)),
]
_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_MONEY = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}")
_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
_SENTENCE = re.compile(r"[^.;\n]+[.;]?")


class DemoProvider:
    name = "demo"
    model = "demo"

    def complete(self, request: AIRequest) -> AIResponse:
        blocks = [b for doc in request.documents for b in doc.blocks]
        properties = (request.output_schema or {}).get("properties", {})
        if "doc_class" in properties:
            return self._json({"doc_class": self._classify(blocks, properties), "confidence": 0.5})
        if "facts" in properties:
            return self._json({"facts": self._facts(blocks)})
        if request.citations:
            return self._summary(blocks)
        return self._json({})

    def _json(self, data: dict[str, Any]) -> AIResponse:
        import json

        return AIResponse(
            parts=[TextPart(json.dumps(data, ensure_ascii=False))],
            model=self.model,
            usage=Usage(),
            json=data,
        )

    def _classify(self, blocks: list[str], properties: dict[str, Any]) -> str:
        allowed = set(properties["doc_class"].get("enum", []))
        text = " ".join(blocks[:5])
        for doc_class, words in _CLASS_KEYWORDS:
            if doc_class in allowed and any(w in text for w in words):
                return doc_class
        return "outro"

    def _facts(self, blocks: list[str]) -> list[dict[str, str]]:
        facts: list[dict[str, str]] = []
        seen: set[str] = set()
        for block in blocks:
            for fact_type, pattern in (
                ("numero_processo", _CNJ),
                ("valor", _MONEY),
                ("data", _DATE),
            ):
                for match in pattern.finditer(block):
                    if match.group(0) in seen:
                        continue
                    seen.add(match.group(0))
                    facts.append(
                        {
                            "type": fact_type,
                            "value": match.group(0),
                            "quote": _sentence_around(block, match.start(), match.end()),
                        }
                    )
        return facts[:25]

    def _summary(self, blocks: list[str]) -> AIResponse:
        parts = [TextPart("Trechos principais\n")]
        for index, block in enumerate(blocks):
            for match in _SENTENCE.finditer(block):
                sentence = " ".join(match.group(0).split())
                if len(sentence) < 40:
                    continue
                parts.append(TextPart(f"{sentence}\n", [Citation(0, index, index + 1, sentence)]))
                if len(parts) > 5:
                    break
            if len(parts) > 5:
                break
        parts.append(TextPart("\nFatos faltantes\n"))
        parts.append(
            TextPart(
                "A IA simulada não identifica lacunas. Configure a IA real para uma análise "
                "completa.\n"
            )
        )
        return AIResponse(parts=parts, model=self.model, usage=Usage())


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right].strip()
