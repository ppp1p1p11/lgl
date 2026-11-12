"""Development preview mode: login from an embedded page under another address."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from legalos.config import Settings, get_settings
from legalos.tenancy.roles import Role
from tests.conftest import PASSWORD


def test_preview_mode_is_refused_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", preview_mode=True)


def test_default_cookie_is_strict(client: TestClient, make_firm, make_member) -> None:
    member = make_member(make_firm("Alfa"), Role.ADVOGADO)
    r = client.post("/api/auth/login", json={"email": member.email, "password": PASSWORD})
    assert "samesite=strict" in r.headers["set-cookie"].lower()


def test_preview_mode_accepts_other_origins_and_relaxes_the_cookie(
    make_firm, make_member, monkeypatch: pytest.MonkeyPatch
) -> None:
    from legalos.main import create_app

    monkeypatch.setenv("LEGALOS_PREVIEW_MODE", "true")
    get_settings.cache_clear()
    try:
        member = make_member(make_firm("Alfa"), Role.ADVOGADO)
        with TestClient(create_app()) as preview:
            body = {"email": member.email, "password": PASSWORD}
            r = preview.post(
                "/api/auth/login", json=body, headers={"Origin": "https://preview.example"}
            )
            assert r.status_code == 200
            cookie = r.headers["set-cookie"].lower()
            assert "samesite=none" in cookie and "secure" in cookie
            r = preview.post(
                "/api/auth/login", json=body, headers={"Origin": "http://localhost:3000"}
            )
            cookie = r.headers["set-cookie"].lower()
            assert "samesite=lax" in cookie and "secure" not in cookie
    finally:
        monkeypatch.delenv("LEGALOS_PREVIEW_MODE")
        get_settings.cache_clear()
