"""Google authorization-code + PKCE OAuth flow.

This module is provider-aware (it knows Google's endpoints and
scopes) but transport-agnostic (it composes URLs and posts JSON; the
caller owns the HTTP client). Reasons for that split:

* Tests can substitute a fake HTTP client without monkey-patching
  ``httpx`` globally.
* Phase 4's Microsoft module reuses the same shape.
* If the operator wants to route OAuth traffic through a proxy,
  the HTTP client is the right injection point.

BYOC config (operator-supplied):
    ``MEMOGRAPH_GOOGLE_CLIENT_ID``
    ``MEMOGRAPH_GOOGLE_CLIENT_SECRET``     (optional — public clients omit)
    ``MEMOGRAPH_GOOGLE_REDIRECT_URI``      (defaults to {server}/api/v1/oauth/google/callback)

The default scope is ``drive.readonly`` — read-only access to Drive
files the user explicitly shares with the integration. Operators who
need write-back (Phase 5+) can override via ``params['scopes']`` on
the source config.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode

from memograph.sources.oauth.token_store import TokenBundle

logger = logging.getLogger(__name__)


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)


@dataclass(frozen=True)
class GoogleOAuthConfig:
    """Operator config for the Google OAuth client."""

    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: tuple[str, ...] = GOOGLE_DEFAULT_SCOPES

    @classmethod
    def from_env(cls, *, default_redirect: str | None = None) -> "GoogleOAuthConfig":
        client_id = os.environ.get("MEMOGRAPH_GOOGLE_CLIENT_ID", "").strip()
        if not client_id:
            raise GoogleOAuthError(
                "MEMOGRAPH_GOOGLE_CLIENT_ID is not set. Configure a "
                "Google OAuth client at console.cloud.google.com → "
                "APIs & Services → Credentials and set the client id "
                "in the environment."
            )
        client_secret = os.environ.get("MEMOGRAPH_GOOGLE_CLIENT_SECRET", "").strip() or None
        redirect_uri = (
            os.environ.get("MEMOGRAPH_GOOGLE_REDIRECT_URI", "").strip()
            or default_redirect
            or ""
        )
        if not redirect_uri:
            raise GoogleOAuthError(
                "Google OAuth redirect URI is not set. Pass "
                "default_redirect= or set MEMOGRAPH_GOOGLE_REDIRECT_URI."
            )
        return cls(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


class GoogleOAuthError(Exception):
    """Raised on any unrecoverable OAuth failure."""


class _HTTPClient(Protocol):
    """Minimal HTTP-client protocol the flow needs.

    httpx.AsyncClient implements it. Tests pass a stub. Keeping the
    surface this small prevents accidental coupling to httpx's
    interceptor / event-hook machinery in the OAuth code, which
    would make it harder to swap in Phase 5.
    """

    async def post(self, url: str, data: dict[str, str]) -> "_HTTPResponse": ...


class _HTTPResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


def build_authorization_url(
    config: GoogleOAuthConfig,
    *,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> str:
    """Compose the user-facing authorization URL.

    ``state`` is opaque to the AS — we round-trip it back on the
    callback. Routes use it to bind the redirect to a previously
    stashed (verifier, source_id, tenant_id) record.

    ``access_type=offline`` is what tells Google to mint a refresh
    token; without it Drive integrations expire after an hour and
    re-prompt for consent. ``prompt=consent`` forces the consent
    screen on every flow so the operator always gets a refresh
    token, even on re-authorisation of an already-granted scope.
    """
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code_for_tokens(
    http: _HTTPClient,
    config: GoogleOAuthConfig,
    *,
    code: str,
    code_verifier: str,
) -> TokenBundle:
    """Exchange an authorization code for tokens.

    Posts to the Google token endpoint. On failure raises
    :class:`GoogleOAuthError` carrying the upstream error body
    verbatim — operators debugging OAuth setup need to see what
    Google said, not our paraphrase.
    """
    data = {
        "code": code,
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret

    resp = await http.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    if resp.status_code != 200:
        raise GoogleOAuthError(
            f"Google token exchange failed ({resp.status_code}): {resp.text}"
        )
    payload = resp.json()
    return _bundle_from_response(payload, scope_fallback=" ".join(config.scopes))


async def refresh_access_token(
    http: _HTTPClient,
    config: GoogleOAuthConfig,
    *,
    refresh_token: str,
) -> TokenBundle:
    """Mint a fresh access token from a saved refresh token.

    Returns a new :class:`TokenBundle`. Google does not always
    return a new refresh token on refresh, so the caller should
    preserve the original refresh_token if the response omits one.
    """
    data = {
        "client_id": config.client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret

    resp = await http.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    if resp.status_code != 200:
        raise GoogleOAuthError(
            f"Google token refresh failed ({resp.status_code}): {resp.text}"
        )
    payload = resp.json()
    bundle = _bundle_from_response(payload, scope_fallback="")
    # Preserve the existing refresh token if Google didn't ship one.
    if bundle.refresh_token is None:
        return TokenBundle(
            access_token=bundle.access_token,
            refresh_token=refresh_token,
            expires_at=bundle.expires_at,
            scope=bundle.scope,
            token_type=bundle.token_type,
            provider=bundle.provider,
            extra=bundle.extra,
        )
    return bundle


def _bundle_from_response(payload: dict[str, Any], *, scope_fallback: str) -> TokenBundle:
    access = payload.get("access_token")
    if not access:
        raise GoogleOAuthError(
            f"Google token response missing access_token: {payload}"
        )
    expires_in = payload.get("expires_in")
    expires_at: datetime | None = None
    if expires_in:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None
    return TokenBundle(
        access_token=access,
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope") or scope_fallback,
        token_type=payload.get("token_type", "Bearer"),
        provider="google",
        extra={k: v for k, v in payload.items() if k.startswith("id_")},
    )


__all__ = [
    "GOOGLE_AUTHORIZATION_ENDPOINT",
    "GOOGLE_DEFAULT_SCOPES",
    "GOOGLE_TOKEN_ENDPOINT",
    "GoogleOAuthConfig",
    "GoogleOAuthError",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "refresh_access_token",
]
