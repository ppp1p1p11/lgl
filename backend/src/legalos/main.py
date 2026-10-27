"""FastAPI application entrypoint: `uvicorn legalos.main:app`."""

from fastapi import FastAPI
from sqlalchemy import text

from legalos.audit.router import router as audit_router
from legalos.auth.deps import DbSession
from legalos.auth.router import router as auth_router
from legalos.config import get_settings
from legalos.core.logging import configure_logging
from legalos.core.middleware import origin_check, security_headers_and_logging
from legalos.tenancy.router import router as firm_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="LegalOS Brasil API",
        version="0.1.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    # Starlette runs the last-added middleware first.
    app.middleware("http")(origin_check(settings.allowed_origins))
    app.middleware("http")(security_headers_and_logging)

    app.include_router(auth_router)
    app.include_router(firm_router)
    app.include_router(audit_router)

    @app.get("/api/health", tags=["system"])
    def health(db: DbSession) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
