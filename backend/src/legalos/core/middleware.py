"""HTTP middleware: security headers, cross-site request protection, request logging."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("legalos.http")

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

Handler = Callable[[Request], Awaitable[Response]]


def origin_check(allowed_origins: list[str]) -> Callable[[Request, Handler], Awaitable[Response]]:
    """Reject state-changing requests sent by a browser from another site (CSRF defence,
    on top of SameSite=Strict cookies). Requests without an Origin header (non-browser
    clients) are allowed; they cannot carry a victim's cookie cross-site."""
    allowed = set(allowed_origins)

    async def middleware(request: Request, call_next: Handler) -> Response:
        origin = request.headers.get("origin")
        if request.method in _UNSAFE_METHODS and origin is not None and origin not in allowed:
            return JSONResponse({"detail": "origin_not_allowed"}, status_code=403)
        return await call_next(request)

    return middleware


async def security_headers_and_logging(request: Request, call_next: Handler) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers["X-Request-ID"] = request_id
    # Path only (no query string), status and timing. Never bodies.
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response
