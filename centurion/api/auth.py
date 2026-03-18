"""Token-based authentication for the Centurion API.

Reads the expected token from the CENTURION_AUTH_TOKEN environment variable.
All endpoints require a valid X-Centurion-Token header except /health and
/health/ready (kept open for monitoring probes).
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response

# Paths that bypass authentication (exact match after stripping trailing slash).
_PUBLIC_PATHS: frozenset[str] = frozenset({"/health", "/health/ready"})


def _is_public(path: str) -> bool:
    """Return True if *path* should be accessible without a token."""
    normalized = path.rstrip("/")
    return normalized in _PUBLIC_PATHS


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces X-Centurion-Token on protected endpoints.

    When ``CENTURION_AUTH_TOKEN`` is **not set**, all requests are allowed
    through (opt-in security).  When the variable is set, every non-public
    request must carry the matching header value.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        token = os.environ.get("CENTURION_AUTH_TOKEN")

        # If no token is configured, skip auth entirely.
        if not token:
            return await call_next(request)

        # Public paths are always allowed.
        if _is_public(request.url.path):
            return await call_next(request)

        # Check header.
        provided = request.headers.get("X-Centurion-Token")
        if not provided:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Centurion-Token header"},
            )

        if not secrets.compare_digest(provided, token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication token"},
            )

        return await call_next(request)
