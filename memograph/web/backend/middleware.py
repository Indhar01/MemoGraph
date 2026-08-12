"""HTTP middleware for the MemoGraph web API.

Covers cross-cutting Phase 1 hardening concerns that don't fit cleanly
into FastAPI's built-in middleware:

- ``RequestIdMiddleware``: per-request UUID propagated via the
  ``X-Request-ID`` response header and stashed on the request scope so
  log records can correlate.
- ``BodySizeLimitMiddleware``: rejects requests with a Content-Length
  larger than ``MEMOGRAPH_MAX_BODY_BYTES`` (default 1 MiB). Streamed
  bodies (Transfer-Encoding: chunked) are *not* enforced here — those
  are bounded at the read site.

Defaults are tuned for a single-tenant VPS deployment (auth provider
TBD, no SSE streams, no large file uploads). Tighten when load
profiles are clearer.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB

REQUEST_ID_HEADER = "X-Request-ID"


def _max_body_bytes() -> int:
    """Resolve the body-size cap from env. Lazy so tests can override."""
    raw = os.environ.get("MEMOGRAPH_MAX_BODY_BYTES")
    if not raw:
        return DEFAULT_MAX_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "MEMOGRAPH_MAX_BODY_BYTES=%r is not an integer; "
            "falling back to default %d",
            raw,
            DEFAULT_MAX_BODY_BYTES,
        )
        return DEFAULT_MAX_BODY_BYTES
    if value < 0:
        logger.warning(
            "MEMOGRAPH_MAX_BODY_BYTES=%d is negative; using default %d",
            value,
            DEFAULT_MAX_BODY_BYTES,
        )
        return DEFAULT_MAX_BODY_BYTES
    return value


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request_id to every request and echo it on the response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Honor a caller-supplied ID if it's a sane UUID; otherwise mint one.
        # We don't blindly trust client headers — if a client sets a 4 KB
        # value, that ends up echoed back into our logs.
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _looks_like_request_id(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _looks_like_request_id(value: str) -> bool:
    # Accept hex UUIDs (with or without dashes) up to 64 chars.
    if not value or len(value) > 64:
        return False
    return all(c.isalnum() or c == "-" for c in value)


class ReadOnlyMiddleware(BaseHTTPMiddleware):
    """Reject body-mutating methods when the server is running read-only.

    Activated by ``MEMOGRAPH_READONLY=true``. Used by the hosted demo
    (Hugging Face Space, public sandbox) so anonymous visitors can browse,
    search, and traverse the graph but cannot mutate the vault.

    Safe methods (``GET``, ``HEAD``, ``OPTIONS``) pass through. Everything
    else returns 403 with a stable error code so the frontend can show a
    "this is a demo, fork it to write" hint instead of a generic failure.

    Health and metrics routes are exempted unconditionally — orchestrators
    poll them with HEAD/GET only, but the exemption is documented so the
    list doesn't drift if future probes use POST.
    """

    _EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/api/health")
    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in self._SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={
                "error": "Server is running in read-only mode",
                "code": "READ_ONLY_MODE",
                "hint": "Set MEMOGRAPH_READONLY=false (or unset) to allow writes.",
            },
        )


def is_readonly_enabled() -> bool:
    """Return True if MEMOGRAPH_READONLY is set to a truthy value."""
    return os.environ.get("MEMOGRAPH_READONLY", "").lower() in {"1", "true", "yes"}


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds the configured cap.

    This relies on ``Content-Length`` and so does *not* protect against
    chunked uploads or clients that lie about the header. Read-site
    bounds and the reverse-proxy's ``client_max_body_size`` are the
    real defense in depth; this middleware just gives a fast, friendly
    rejection for the common case.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        max_bytes = _max_body_bytes()
        if max_bytes == 0:
            # Explicit opt-out: disable the check entirely.
            return await call_next(request)

        content_length_header = request.headers.get("content-length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Malformed Content-Length header",
                        "code": "BAD_REQUEST",
                    },
                )
            if content_length > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Request body too large",
                        "code": "PAYLOAD_TOO_LARGE",
                        "limit_bytes": max_bytes,
                    },
                )
        return await call_next(request)


__all__ = [
    "RequestIdMiddleware",
    "BodySizeLimitMiddleware",
    "ReadOnlyMiddleware",
    "is_readonly_enabled",
    "DEFAULT_MAX_BODY_BYTES",
    "REQUEST_ID_HEADER",
]


# Re-export ASGIApp for static checkers that complain about unused imports.
_ = ASGIApp
