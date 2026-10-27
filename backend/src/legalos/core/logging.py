"""Structured JSON logs with personal data scrubbed (brief §8).

Logs must never contain document text, raw prompts, passwords, tokens, or identifiers
such as CPF/CNPJ/email. Code should not log those in the first place; this filter is a
safety net for mistakes.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[cnpj]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[cpf]"),
    (re.compile(r"\b\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}\b"), "[processo]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?i)(bearer\s+)[\w.~+/=-]+"), r"\1[token]"),
    (re.compile(r"(?i)(legalos_session=)[^;\s]+"), r"\1[token]"),
]

_SENSITIVE_KEYS = {"password", "token", "secret", "code", "recovery_code", "cookie"}

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def scrub(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _scrub_any(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, str):
        return scrub(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = _scrub_any(key, value)
        if record.exc_info:
            entry["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn's access log includes query strings; we log requests ourselves instead.
    logging.getLogger("uvicorn.access").disabled = True
