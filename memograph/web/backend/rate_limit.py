"""Rate limiting setup for the MemoGraph web API.

Phase 1 ships per-IP rate limiting using slowapi. When auth lands in
Phase 1.1, the key function will switch to "<api-key>:<ip>" so a single
shared NAT'd network of legitimate clients isn't punished collectively.

Configuration env vars:

    MEMOGRAPH_RATELIMIT_DEFAULT
        Default per-route limit, slowapi format. Default "60/minute".
    MEMOGRAPH_RATELIMIT_STORAGE
        slowapi storage URI. Defaults to "memory://", which is fine for
        a single-process VPS deployment. For horizontally-scaled
        deployments, point at Redis: "redis://redis:6379/0".
    MEMOGRAPH_RATELIMIT_DISABLED
        "1"/"true"/"yes" disables rate limiting entirely. Use only for
        local development or when fronted by a rate-limiting proxy
        (Cloudflare, nginx ratelimit module, etc.).

Apply per-route overrides with::

    from .rate_limit import limiter
    @router.get("/expensive")
    @limiter.limit("5/minute")
    async def expensive(request: Request): ...
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = os.environ.get("MEMOGRAPH_RATELIMIT_DEFAULT", "60/minute")
STORAGE_URI = os.environ.get("MEMOGRAPH_RATELIMIT_STORAGE", "memory://")
DISABLED = os.environ.get("MEMOGRAPH_RATELIMIT_DISABLED", "").lower() in {
    "1",
    "true",
    "yes",
}


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[] if DISABLED else [DEFAULT_LIMIT],
    storage_uri=STORAGE_URI,
    # When the limiter cannot reach its backend (e.g. Redis is down),
    # fail open rather than 500-ing every request. Document the
    # tradeoff: better availability under storage failure, slightly
    # weaker rate-limit guarantee.
    swallow_errors=True,
)


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """429 response with Retry-After and a structured JSON body.

    slowapi's default handler returns a plain string body; this version
    matches the rest of our API error envelope (`error`/`code`) and
    surfaces the configured limit so legitimate clients can back off
    intelligently.
    """
    retry_after = getattr(exc, "retry_after", None)
    headers = {"Retry-After": str(int(retry_after))} if retry_after else {}
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "code": "RATE_LIMITED",
            "limit": str(exc.detail),
        },
        headers=headers,
    )
