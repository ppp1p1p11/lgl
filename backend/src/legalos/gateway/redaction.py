"""Replace personal identifiers with placeholders before text leaves our systems, and put
them back in the answer (brief §4: redact or minimize personal data).

Names are deliberately not redacted: legal summaries need them and name detection is
unreliable. What is removed: CPF, CNPJ (incl. alphanumeric), RG, OAB registration,
e-mail, phone numbers and CEP. Case numbers (CNJ) are kept: they are needed for the work.
"""

import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CNPJ", re.compile(r"\b[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}\b")),
    ("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("RG", re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b")),
    (
        "OAB",
        re.compile(r"\bOAB\s*/?\s*[A-Z]{2}\s*(?:n[ºo°.]\s*)?\d{1,3}\.?\d{3}\b", re.IGNORECASE),
    ),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("TELEFONE", re.compile(r"\(\d{2}\)\s?9?\d{4}-?\d{4}\b|\b\d{2}\s9\d{4}-\d{4}\b")),
    ("CEP", re.compile(r"\b\d{5}-\d{3}\b")),
]

_PLACEHOLDER = re.compile(r"\[(CNPJ|CPF|RG|OAB|EMAIL|TELEFONE|CEP)_\d+\]")


@dataclass
class Redactor:
    """One per AI call. The same value always gets the same placeholder."""

    enabled: bool = True
    _by_value: dict[str, str] = field(default_factory=dict)
    _by_placeholder: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self._by_value)

    def redact(self, text: str) -> str:
        if not self.enabled:
            return text
        for label, pattern in _PATTERNS:

            def replace(match: re.Match[str], label: str = label) -> str:
                return self._placeholder(label, match.group(0))

            text = pattern.sub(replace, text)
        return text

    def _placeholder(self, label: str, value: str) -> str:
        if value in self._by_value:
            return self._by_value[value]
        n = sum(1 for p in self._by_placeholder if p.startswith(f"[{label}_")) + 1
        placeholder = f"[{label}_{n}]"
        self._by_value[value] = placeholder
        self._by_placeholder[placeholder] = value
        return placeholder

    def restore(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: self._by_placeholder.get(m.group(0), m.group(0)), text)
