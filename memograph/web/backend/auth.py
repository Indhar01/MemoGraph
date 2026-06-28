"""Authentication for the MemoGraph web API.

Provider-neutral by design: the same code path serves WorkOS, Auth0,
Clerk, Keycloak, or any other OIDC issuer that publishes a JWKS
endpoint. The provider is chosen at deploy time via env vars; nothing
in the codebase is vendor-locked.

Three modes, picked via ``MEMOGRAPH_AUTH_PROVIDER``:

- ``none`` (default, with a loud startup warning): no auth. Fine for
  ``docker compose up`` on localhost; absolutely not for production.
- ``api_key``: the request must carry ``X-API-Key`` matching one of the
  hashed entries in ``MEMOGRAPH_API_KEYS``. Service-to-service.
- ``oidc``: ``Authorization: Bearer <jwt>`` validated against
  ``MEMOGRAPH_OIDC_JWKS_URL`` with audience pinned to
  ``MEMOGRAPH_OIDC_AUDIENCE`` (and optionally issuer to
  ``MEMOGRAPH_OIDC_ISSUER``). Browser flows.
- ``multi``: accept either credential. Common in mixed deployments.

The dependency ``require_user`` injects a :class:`User` into route
handlers and stashes the same identity on a ``ContextVar`` so the
audit log (``Action.user``) populates without threading the user
through every kernel call.

When auth is enabled but a request fails verification, a 401 is
returned with the ``WWW-Authenticate`` header set per RFC 6750. We
never echo *why* a token failed (expiry vs signature vs audience) to
the client — that information is logged server-side only, since it
helps attackers fingerprint the verification logic.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

# Algorithms we accept. Excludes "none" (unsigned) and HMAC variants —
# OIDC providers publish public keys via JWKS and we should never accept
# an HMAC-signed token because then the JWKS endpoint becomes a credential.
_ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")

# Small leeway on `iat`/`exp` to absorb clock skew between the IdP and us.
_JWT_LEEWAY_SECONDS = 30


class AuthProvider(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    OIDC = "oidc"
    MULTI = "multi"

    @classmethod
    def from_env(cls) -> AuthProvider:
        raw = os.environ.get("MEMOGRAPH_AUTH_PROVIDER", "none").lower().strip()
        try:
            return cls(raw)
        except ValueError:
            logger.warning(
                "MEMOGRAPH_AUTH_PROVIDER=%r is not a valid provider; "
                "defaulting to 'none'. Valid: %s",
                raw,
                [p.value for p in cls],
            )
            return cls.NONE


@dataclass(frozen=True)
class User:
    """Authenticated identity injected into every authorised route.

    ``id`` is the stable subject identifier (``sub`` claim for OIDC,
    a hash for API keys). ``email`` may be empty for service tokens.
    ``organization_id`` is reserved for Phase 3 tenant mapping — the
    OIDC ``org_id`` claim flows through here today even though the
    tenant primitive doesn't exist yet, so the audit log captures it.
    """

    id: str
    email: str = ""
    organization_id: str = ""
    scopes: tuple[str, ...] = ()
    raw_claims: dict[str, Any] = field(default_factory=dict)


# Per-request identity for non-route consumers (action logger, kernel).
# Cleared after each request by the dependency.
current_user: ContextVar[User | None] = ContextVar("current_user", default=None)


# --------------------------------------------------------------------- API KEY


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _hashed_api_keys() -> list[bytes]:
    """Resolve the configured API key allowlist as sha256 digests.

    Plaintext keys live in ``MEMOGRAPH_API_KEYS`` (comma-separated);
    we hash them at access time and compare hashes constant-time so a
    timing oracle on the comparison can't leak which prefix matched.
    """
    raw = os.environ.get("MEMOGRAPH_API_KEYS", "").strip()
    if not raw:
        return []
    return [
        hashlib.sha256(k.strip().encode("utf-8")).digest()
        for k in raw.split(",")
        if k.strip()
    ]


def _verify_api_key(presented: str) -> User | None:
    presented_hash = hashlib.sha256(presented.encode("utf-8")).digest()
    for known in _hashed_api_keys():
        if hmac.compare_digest(known, presented_hash):
            # The "id" we record is the prefix of the key hash, never the
            # plaintext. Enough to disambiguate clients in audit logs
            # without storing the credential.
            return User(
                id=f"apikey:{known.hex()[:12]}",
                email="",
                scopes=("api_key",),
            )
    return None


# ------------------------------------------------------------------------ OIDC


_bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    """Lazy-build the JWKS client; cached forever. Tests reset via
    :func:`_reset_oidc_state`."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    url = os.environ.get("MEMOGRAPH_OIDC_JWKS_URL", "").strip()
    if not url:
        return None
    _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=600)
    return _jwks_client


def _reset_oidc_state() -> None:
    """Test helper: drop the cached JWKS client so env changes take effect."""
    global _jwks_client
    _jwks_client = None


def _verify_oidc_token(token: str) -> User | None:
    audience = os.environ.get("MEMOGRAPH_OIDC_AUDIENCE", "").strip()
    issuer = os.environ.get("MEMOGRAPH_OIDC_ISSUER", "").strip() or None
    if not audience:
        logger.error(
            "MEMOGRAPH_OIDC_AUDIENCE is empty; refusing every token "
            "(unbound audience is a credential-confusion risk)"
        )
        return None

    client = _get_jwks_client()
    if client is None:
        logger.error("MEMOGRAPH_OIDC_JWKS_URL is empty; OIDC mode cannot run")
        return None

    try:
        signing_key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=list(_ALLOWED_ALGS),
            audience=audience,
            issuer=issuer,
            leeway=_JWT_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        # Log the *type* of failure server-side; never the token.
        logger.info("OIDC verification failed: %s", type(exc).__name__)
        return None
    except Exception as exc:  # pragma: no cover — JWKS network errors etc.
        logger.warning("OIDC verification raised %s", type(exc).__name__)
        return None

    sub = str(claims.get("sub") or "")
    email = str(claims.get("email") or "")
    org = str(claims.get("org_id") or claims.get("organization_id") or "")
    scope_claim = claims.get("scope") or claims.get("scp") or ""
    if isinstance(scope_claim, str):
        scopes = tuple(s for s in scope_claim.split() if s)
    elif isinstance(scope_claim, list):
        scopes = tuple(str(s) for s in scope_claim)
    else:
        scopes = ()

    return User(
        id=f"oidc:{sub}" if sub else "",
        email=email,
        organization_id=org,
        scopes=scopes,
        raw_claims=claims,
    )


# ----------------------------------------------------------- DEPENDENCY ENTRY


_AUTH_FAILURE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentication required",
    headers={"WWW-Authenticate": 'Bearer realm="memograph"'},
)


_warned_no_auth = False


def _warn_open_api_once() -> None:
    global _warned_no_auth
    if _warned_no_auth:
        return
    _warned_no_auth = True
    logger.warning(
        "MEMOGRAPH_AUTH_PROVIDER is 'none' — the API is OPEN. "
        "Set MEMOGRAPH_AUTH_PROVIDER=oidc|api_key|multi for production."
    )


async def require_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    api_key: str | None = Depends(_api_key_header),
) -> User:
    """FastAPI dependency: 401 unless a valid credential is presented.

    When ``MEMOGRAPH_AUTH_PROVIDER=none``, returns an anonymous user
    rather than failing — useful for local-dev workflows. A startup
    warning fires once so this isn't silent.
    """
    provider = AuthProvider.from_env()

    if provider is AuthProvider.NONE:
        _warn_open_api_once()
        # When auth is off, the API is wide open anyway — giving the
        # anonymous user the "admin" scope so admin-gated routes
        # (source registration, connect-session, deletes) work in
        # local dev. Production deployments MUST set
        # MEMOGRAPH_AUTH_PROVIDER to api_key or oidc instead of
        # relying on this; the startup warning fires above.
        anon = User(id="anonymous", email="", scopes=("anonymous", "admin"))
        current_user.set(anon)
        request.state.user = anon
        return anon

    user: User | None = None
    if provider in (AuthProvider.API_KEY, AuthProvider.MULTI) and api_key:
        user = _verify_api_key(api_key)
    if (
        user is None
        and provider in (AuthProvider.OIDC, AuthProvider.MULTI)
        and bearer is not None
    ):
        user = _verify_oidc_token(bearer.credentials)

    if user is None:
        raise _AUTH_FAILURE

    current_user.set(user)
    request.state.user = user
    return user


async def optional_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    api_key: str | None = Depends(_api_key_header),
) -> User | None:
    """Like :func:`require_user` but never 401s. Returns ``None`` when
    no credential is provided; useful for endpoints that *log* identity
    when present but should remain anonymous-friendly."""
    provider = AuthProvider.from_env()
    if provider is AuthProvider.NONE:
        return None
    user: User | None = None
    if provider in (AuthProvider.API_KEY, AuthProvider.MULTI) and api_key:
        user = _verify_api_key(api_key)
    if (
        user is None
        and provider in (AuthProvider.OIDC, AuthProvider.MULTI)
        and bearer is not None
    ):
        user = _verify_oidc_token(bearer.credentials)
    if user is not None:
        current_user.set(user)
        request.state.user = user
    return user


def require_scope(*needed: str):
    """Build a dependency that 403s if the user lacks every named scope."""

    async def _checker(user: User = Depends(require_user)) -> User:
        missing = tuple(s for s in needed if s not in user.scopes)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope(s): {', '.join(missing)}",
            )
        return user

    return _checker


__all__ = [
    "AuthProvider",
    "User",
    "current_user",
    "require_user",
    "optional_user",
    "require_scope",
]
