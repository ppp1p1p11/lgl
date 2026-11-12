import json
import logging

from legalos.core.logging import JsonFormatter, scrub


def test_scrub_personal_identifiers() -> None:
    text = (
        "cliente CPF 123.456.789-09, empresa CNPJ 12.345.678/0001-95, "
        "email fulano@exemplo.com.br, processo 0001234-56.2024.8.26.0100"
    )
    out = scrub(text)
    for secret in ("123.456.789-09", "12.345.678/0001-95", "fulano@exemplo", "0001234-56"):
        assert secret not in out
    assert "[cpf]" in out and "[cnpj]" in out and "[email]" in out and "[processo]" in out


def test_scrub_tokens() -> None:
    assert "abc123" not in scrub("Authorization: Bearer abc123")
    assert "abc123" not in scrub("cookie: legalos_session=abc123; other=1")


def test_formatter_redacts_sensitive_fields() -> None:
    record = logging.makeLogRecord(
        {"msg": "login de fulano@exemplo.com", "password": "hunter2", "path": "/api/x"}
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["password"] == "[redacted]"
    assert entry["msg"] == "login de [email]"
    assert entry["path"] == "/api/x"
