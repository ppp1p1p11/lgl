"""Application settings, read from environment variables (see `.env.example`)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEGALOS_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # Runtime connection: the restricted application role (no table ownership, no BYPASSRLS).
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://legalos_app:legalos_app@localhost:5432/legalos"
    )
    # Migration / provisioning connection: the table-owner role. Never used to serve requests.
    database_owner_url: SecretStr = SecretStr(
        "postgresql+psycopg://legalos_owner:legalos_owner@localhost:5432/legalos"
    )
    # Name of the application role that migrations grant privileges to.
    database_app_role: str = "legalos_app"

    # Key for column-level encryption (MFA secrets, later CPF/CNPJ). Fernet key, urlsafe base64.
    encryption_key: SecretStr = SecretStr("")

    # Browser origins allowed to make state-changing requests.
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Must be true outside local development (cookie only sent over HTTPS).
    session_cookie_secure: bool = True
    session_ttl_hours: int = 12
    pending_mfa_ttl_minutes: int = 10

    # Login throttling.
    login_max_failures: int = 5
    login_window_minutes: int = 15
    mfa_max_failures: int = 5

    # S3-compatible object storage (SeaweedFS locally, a Brazilian region in production).
    storage_endpoint_url: str | None = "http://localhost:8333"
    storage_public_endpoint_url: str | None = None
    storage_region: str = "sa-east-1"
    storage_bucket: str = "legalos-documents"
    storage_access_key: SecretStr = SecretStr("")
    storage_secret_key: SecretStr = SecretStr("")
    # Server-side encryption for uploaded objects, e.g. "AES256" or "aws:kms". None for local dev.
    storage_sse: str | None = None
    signed_url_ttl_seconds: int = 300

    log_level: str = "INFO"

    # Worker
    worker_poll_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
