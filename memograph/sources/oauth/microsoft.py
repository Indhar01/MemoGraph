"""Microsoft Entra (Azure AD) authorization-code + PKCE OAuth flow.

Mirrors :mod:`memograph.sources.oauth.google` so the rest of the
codebase can stay symmetric. Microsoft's twist on the spec is the
*tenant segment* of the authorization URL: the value picks which
directory issues the token. We support the three common settings:

* ``common`` — any Entra tenant + personal Microsoft accounts (default)
* ``organizations`` — work / school accounts only
* ``consumers`` — personal accounts only
* A concrete tenant id (GUID or verified domain) — single-tenant apps

BYOC config (operator-supplied):
    ``MEMOGRAPH_MICROSOFT_CLIENT_ID``
    ``MEMOGRAPH_MICROSOFT_CLIENT_SECRET``  (optional — public clients omit)
    ``MEMOGRAPH_MICROSOFT_REDIRECT_URI``   (defaults to {server}/api/v1/oauth/microsoft/callback)
    ``MEMOGRAPH_MICROSOFT_TENANT``         (defaults to "common")

The default scope is ``Files.Read offline_access`` — read-only access
to OneDrive / SharePoint files the user owns or that have been shared
with them. ``offline_access`` is the magic Microsoft scope that mints
a refresh token; without it the integration silently expires after an
hour. Operators who need write-back can override via
``params['scopes']`` on the source config.
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


MICROSOFT_DEFAULT_TENANT = "common"
MICROSOFT_DEFAULT_SCOPES = ("Files.Read", "offline_access")


def _authorization_endpoint(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"


def _token_endpoint(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


@dataclass(frozen=True)
class MicrosoftOAuthConfig:
    """Operator config for the Microsoft OAuth client."""

    client_id: str
    client_secret: str | None
    redirect_uri: str
    tenant: str = MICROSOFT_DEFAULT_TENANT
    scopes: tuple[str, ...] = MICROSOFT_DEFAULT_SCOPES

    @property
    def authorization_endpoint(self) -> str:
        return _authorization_endpoint(self.tenant)

    @property
    def token_endpoint(self) -> str:
        return _token_endpoint(self.tenant)

    @classmethod
    def from_env(cls, *, default_redirect: str | None = None) -> "MicrosoftOAuthConfig":
        client_id = os.environ.get("MEMOGRAPH_MICROSOFT_CLIENT_ID", "").strip()
        if not client_id:
            raise MicrosoftOAuthError(
                "MEMOGRAPH_MICROSOFT_CLIENT_ID is not set. Register an "
                "app at https://portal.azure.com → Entra ID → App "
                "registrations and set the (Application) client id in "
                "the environment."
            )
        client_secret = (
            os.environ.get("MEMOGRAPH_MICROSOFT_CLIENT_SECRET", "").strip() or None
        )
        redirect_uri = (
            os.environ.get("MEMOGRAPH_MICROSOFT_REDIRECT_URI", "").strip()
            or default_redirect
            or ""
        )
        if not redirect_uri:
            raise MicrosoftOAuthError(
                "Microsoft OAuth redirect URI is not set. Pass "
                "default_redirect= or set MEMOGRAPH_MICROSOFT_REDIRECT_URI."
            )
        tenant = (
            os.environ.get("MEMOGRAPH_MICROSOFT_TENANT", "").strip()
            or MICROSOFT_DEFAULT_TENANT
        )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            tenant=tenant,
        )


class MicrosoftOAuthError(Exception):
    """Raised on any unrecoverable OAuth failure."""


class _HTTPClient(Protocol):
    async def post(self, url: str, data: dict[str, str]) -> "_HTTPResponse": ...


class _HTTPResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


def build_authorization_url(
    config: MicrosoftOAuthConfig,
    *,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> str:
    """Compose the user-facing authorization URL.

    Microsoft accepts ``response_mode=query`` for browser-based flows;
    the default is ``query`` for confidential clients and ``fragment``
    for public ones, so we pin it for predictability. ``prompt=select_account``
    forces the account chooser even when the browser already has a
    session — important when the operator has both a personal and a
    work account in the same browser.
    """
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "prompt": "select_account",
    }
    return f"{config.authorization_endpoint}?{urlencode(params)}"


async def exchange_code_for_tokens(
    http: _HTTPClient,
    config: MicrosoftOAuthConfig,
    *,
    code: str,
    code_verifier: str,
) -> TokenBundle:
    """Exchange an authorization code for tokens.

    Raises :class:`MicrosoftOAuthError` with the verbatim upstream body
    on failure — operators chasing AADSTS error codes need to see them.
    """
    data = {
        "code": code,
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
        "scope": " ".join(config.scopes),
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret

    resp = await http.post(config.token_endpoint, data=data)
    if resp.status_code != 200:
        raise MicrosoftOAuthError(
            f"Microsoft token exchange failed ({resp.status_code}): {resp.text}"
        )
    payload = resp.json()
    return _bundle_from_response(payload, scope_fallback=" ".join(config.scopes))


async def refresh_access_token(
    http: _HTTPClient,
    config: MicrosoftOAuthConfig,
    *,
    refresh_token: str,
) -> TokenBundle:
    """Mint a fresh access token from a saved refresh token.

    Microsoft *does* tend to ship a new refresh token on every refresh
    (rolling refresh tokens), but we still defensively preserve the
    original if the response omits one — same shape as the Google
    flow, keeps the adapter glue simple.
    """
    data = {
        "client_id": config.client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": " ".join(config.scopes),
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret

    resp = await http.post(config.token_endpoint, data=data)
    if resp.status_code != 200:
        raise MicrosoftOAuthError(
            f"Microsoft token refresh failed ({resp.status_code}): {resp.text}"
        )
    payload = resp.json()
    bundle = _bundle_from_response(payload, scope_fallback="")
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
        raise MicrosoftOAuthError(
            f"Microsoft token response missing access_token: {payload}"
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
        provider="microsoft",
        extra={k: v for k, v in payload.items() if k.startswith("id_")},
    )


__all__ = [
    "MICROSOFT_DEFAULT_SCOPES",
    "MICROSOFT_DEFAULT_TENANT",
    "MicrosoftOAuthConfig",
    "MicrosoftOAuthError",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "refresh_access_token",
]
