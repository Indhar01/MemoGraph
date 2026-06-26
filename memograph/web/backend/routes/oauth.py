"""OAuth start + callback routes for cloud Source adapters.

Phase 3 wires Google; Phase 4 will add Microsoft on the same shape.
Routes live under ``/api/v1/oauth/{provider}/...``:

* ``GET  /start`` — admin-scoped. Mints a state token + PKCE verifier
  pair, persists the binding to memory, returns the authorization URL.
* ``GET  /callback`` — public (the AS redirects here). Validates the
  state, exchanges the code for tokens, persists the encrypted bundle,
  redirects the browser back to the frontend.

State + verifier are held in process memory only — the OAuth flow
finishes in seconds and surviving a server restart mid-flow is not
worth the persistence complexity. Lost state == user retries.

The encryption key for the token store comes from
``MEMOGRAPH_SECRET_KEY``. If the variable is unset, the start route
returns 503 with a clear setup message; this is preferred over
silently writing tokens that can't be decrypted after a key rotation.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from memograph.sources import audit
from memograph.sources.base import SourceConfig, SourceKind
from memograph.sources.oauth.google import (
    GoogleOAuthConfig,
    GoogleOAuthError,
    build_authorization_url,
    exchange_code_for_tokens,
)
from memograph.sources.oauth.microsoft import (
    MicrosoftOAuthConfig,
    MicrosoftOAuthError,
)
from memograph.sources.oauth.microsoft import (
    build_authorization_url as ms_build_authorization_url,
)
from memograph.sources.oauth.microsoft import (
    exchange_code_for_tokens as ms_exchange_code_for_tokens,
)
from memograph.sources.oauth.pkce import new_pkce_challenge
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenStoreError,
)
from memograph.web.backend.auth import User, require_scope
from memograph.web.backend.tenant_resolver import (
    SINGLE_TENANT_ID,
    resolve_tenant_id,
)

logger = logging.getLogger("memograph.api.oauth")

router = APIRouter(prefix="/oauth", tags=["oauth"])


_FLOW_TTL = timedelta(minutes=10)
"""Authorization flows must complete within this window. Anything
longer is almost certainly an abandoned tab — the in-memory state
gets garbage-collected on the next start."""


@dataclass
class _PendingFlow:
    """In-flight OAuth state. Wiped on callback or TTL expiry."""

    provider: str
    source_id: str
    tenant_id: str | None
    code_verifier: str
    user_id: str
    created_at: datetime
    display_name: str
    params: dict[str, Any]


class StartOAuthResponse(BaseModel):
    authorization_url: str
    state: str
    expires_in_seconds: int


def _pending_flows(request: Request) -> dict[str, _PendingFlow]:
    """Lazy per-app cache of in-flight OAuth flows.

    Bound to ``app.state.oauth_pending`` so the dict survives across
    requests within the same uvicorn worker. Multi-worker deployments
    will lose flows when the start + callback hit different workers —
    a known Phase-5 follow-up; for single-worker dev that's fine.
    """
    store = getattr(request.app.state, "oauth_pending", None)
    if store is None:
        store = {}
        request.app.state.oauth_pending = store
    # Cheap GC of expired flows on every access. The list is tiny
    # (a handful in flight at most) so this is fine.
    cutoff = datetime.now(timezone.utc) - _FLOW_TTL
    for state in list(store.keys()):
        if store[state].created_at < cutoff:
            del store[state]
    return store


def _tenant_for(request: Request, user: User) -> str | None:
    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        return None
    tid = resolve_tenant_id(request, user)
    return None if tid == SINGLE_TENANT_ID else tid


def _sources_dir_for(request: Request, tenant_id: str | None):
    registry = getattr(request.app.state, "source_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "sources subsystem is disabled. "
                "Set MEMOGRAPH_SOURCES_ENABLED=1 to enable."
            ),
        )
    return registry._sources_dir(tenant_id), registry


@router.get("/google/start", response_model=StartOAuthResponse)
async def google_start(
    request: Request,
    source_id: str = Query(..., min_length=1, max_length=64),
    display_name: str = Query("Google Drive", min_length=1, max_length=128),
    folder_id: str | None = Query(None),
    user: User = Depends(require_scope("admin")),
) -> StartOAuthResponse:
    """Begin an OAuth flow for a Google Drive source.

    Returns the user-facing authorization URL. The frontend
    redirects the user to it; Google redirects back to
    ``/google/callback`` on success or to the ``error`` page on
    denial.
    """
    tenant_id = _tenant_for(request, user)
    sources_dir, _ = _sources_dir_for(request, tenant_id)

    # Build the OAuth config from env. The redirect URI must match
    # exactly what's configured at console.cloud.google.com for the
    # operator's OAuth client — we accept the operator's override
    # via env but synthesize a default that points at this same
    # server's callback path.
    base = str(request.base_url).rstrip("/")
    default_redirect = f"{base}/api/v1/oauth/google/callback"
    try:
        oauth_config = GoogleOAuthConfig.from_env(default_redirect=default_redirect)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # Ensure the secret-key for the token store is set BEFORE we
    # build the URL, so an end user doesn't go through the consent
    # flow only to have us fail on callback because we can't store.
    try:
        EncryptedTokenStore(sources_dir)
    except TokenStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    pkce = new_pkce_challenge()
    state = secrets.token_urlsafe(32)
    pending = _pending_flows(request)
    pending[state] = _PendingFlow(
        provider="google",
        source_id=source_id,
        tenant_id=tenant_id,
        code_verifier=pkce.verifier,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        display_name=display_name,
        params={"folder_id": folder_id} if folder_id else {},
    )

    url = build_authorization_url(
        oauth_config,
        state=state,
        code_challenge=pkce.challenge,
        code_challenge_method=pkce.method,
    )
    return StartOAuthResponse(
        authorization_url=url,
        state=state,
        expires_in_seconds=int(_FLOW_TTL.total_seconds()),
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """Complete the Google OAuth flow.

    This route is intentionally NOT scope-gated — Google redirects
    the user here directly and the state-binding is what proves
    legitimacy. Anyone with a stolen state + matching code could
    complete the flow, but the state is sent over TLS in the
    redirect and discarded on first use; replay is bounded by the
    10-minute TTL.

    Returns a redirect to the frontend's sources page. The frontend
    URL is taken from the env var ``MEMOGRAPH_FRONTEND_URL`` or
    falls back to ``/`` on the same host.
    """
    pending = _pending_flows(request)

    if error:
        # User clicked "deny" or Google rejected the request. The
        # error param is what Google sent; we surface it on the
        # frontend so the user knows why.
        return _redirect_to_frontend(request, error=error)

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing code or state",
        )

    flow = pending.pop(state, None)
    if flow is None or flow.provider != "google":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "unknown or expired state; restart the flow from "
                "the sources page"
            ),
        )

    try:
        oauth_config = GoogleOAuthConfig.from_env(
            default_redirect=f"{str(request.base_url).rstrip('/')}/api/v1/oauth/google/callback",
        )
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    sources_dir, registry = _sources_dir_for(request, flow.tenant_id)
    try:
        store = EncryptedTokenStore(sources_dir)
    except TokenStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # Exchange code → tokens. We rely on httpx as the transport.
    try:
        import httpx
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="httpx is required for OAuth flows; install memograph[sources-gdrive]",
        ) from exc

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            bundle = await exchange_code_for_tokens(
                _HttpxAdapter(client),
                oauth_config,
                code=code,
                code_verifier=flow.code_verifier,
            )
        except GoogleOAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    store.save(flow.source_id, bundle)

    # Now that the tokens are on disk, register the source in the
    # registry so the user doesn't have to take a second action.
    config = SourceConfig(
        source_id=flow.source_id,
        kind=SourceKind.GDRIVE,
        display_name=flow.display_name,
        tenant_id=flow.tenant_id,
        params=flow.params,
    )
    registry.register(config)

    audit.record(
        sources_dir=sources_dir,
        action=audit.ACTION_OAUTH_EXCHANGE,
        source_id=flow.source_id,
        source_kind="gdrive",
        user_id=flow.user_id,
        tenant_id=flow.tenant_id,
        request_id=getattr(request.state, "request_id", None),
        after={"scope": bundle.scope, "has_refresh_token": bool(bundle.refresh_token)},
    )

    return _redirect_to_frontend(request, source_id=flow.source_id)


@router.get("/microsoft/start", response_model=StartOAuthResponse)
async def microsoft_start(
    request: Request,
    source_id: str = Query(..., min_length=1, max_length=64),
    display_name: str = Query("OneDrive", min_length=1, max_length=128),
    drive_id: str | None = Query(None),
    folder_id: str | None = Query(None),
    user: User = Depends(require_scope("admin")),
) -> StartOAuthResponse:
    """Begin an OAuth flow for a OneDrive / SharePoint source.

    Mirror of :func:`google_start` against the Microsoft Entra
    endpoints. The flow lives in the same in-memory pending-dict; the
    ``provider`` field on :class:`_PendingFlow` discriminates the two
    so a stale Google state can't be consumed by the MS callback.
    """
    tenant_id = _tenant_for(request, user)
    sources_dir, _ = _sources_dir_for(request, tenant_id)

    base = str(request.base_url).rstrip("/")
    default_redirect = f"{base}/api/v1/oauth/microsoft/callback"
    try:
        oauth_config = MicrosoftOAuthConfig.from_env(default_redirect=default_redirect)
    except MicrosoftOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        EncryptedTokenStore(sources_dir)
    except TokenStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    pkce = new_pkce_challenge()
    state = secrets.token_urlsafe(32)
    params: dict[str, Any] = {}
    if drive_id:
        params["drive_id"] = drive_id
    if folder_id:
        params["folder_id"] = folder_id
    pending = _pending_flows(request)
    pending[state] = _PendingFlow(
        provider="microsoft",
        source_id=source_id,
        tenant_id=tenant_id,
        code_verifier=pkce.verifier,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        display_name=display_name,
        params=params,
    )

    url = ms_build_authorization_url(
        oauth_config,
        state=state,
        code_challenge=pkce.challenge,
        code_challenge_method=pkce.method,
    )
    return StartOAuthResponse(
        authorization_url=url,
        state=state,
        expires_in_seconds=int(_FLOW_TTL.total_seconds()),
    )


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """Complete the Microsoft OAuth flow.

    Entra surfaces ``error_description`` alongside the ``error`` code
    on a denial; we forward both to the frontend so the user sees the
    AADSTS message rather than a bare error slug.
    """
    pending = _pending_flows(request)

    if error:
        msg = f"{error}: {error_description}" if error_description else error
        return _redirect_to_frontend(request, error=msg)

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing code or state",
        )

    flow = pending.pop(state, None)
    if flow is None or flow.provider != "microsoft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "unknown or expired state; restart the flow from "
                "the sources page"
            ),
        )

    try:
        oauth_config = MicrosoftOAuthConfig.from_env(
            default_redirect=(
                f"{str(request.base_url).rstrip('/')}/api/v1/oauth/microsoft/callback"
            ),
        )
    except MicrosoftOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    sources_dir, registry = _sources_dir_for(request, flow.tenant_id)
    try:
        store = EncryptedTokenStore(sources_dir)
    except TokenStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        import httpx
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="httpx is required for OAuth flows; install memograph[sources-onedrive]",
        ) from exc

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            bundle = await ms_exchange_code_for_tokens(
                _HttpxAdapter(client),
                oauth_config,
                code=code,
                code_verifier=flow.code_verifier,
            )
        except MicrosoftOAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    store.save(flow.source_id, bundle)

    config = SourceConfig(
        source_id=flow.source_id,
        kind=SourceKind.ONEDRIVE,
        display_name=flow.display_name,
        tenant_id=flow.tenant_id,
        params=flow.params,
    )
    registry.register(config)

    audit.record(
        sources_dir=sources_dir,
        action=audit.ACTION_OAUTH_EXCHANGE,
        source_id=flow.source_id,
        source_kind="onedrive",
        user_id=flow.user_id,
        tenant_id=flow.tenant_id,
        request_id=getattr(request.state, "request_id", None),
        after={"scope": bundle.scope, "has_refresh_token": bool(bundle.refresh_token)},
    )

    return _redirect_to_frontend(request, source_id=flow.source_id)


class _HttpxAdapter:
    """Lightweight adapter so the OAuth module can stay httpx-agnostic."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def post(self, url: str, data: dict[str, str]) -> Any:
        return await self._client.post(url, data=data)


def _redirect_to_frontend(
    request: Request,
    *,
    source_id: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Build a redirect URL back to the frontend's sources page.

    Operators with a separate frontend origin set
    ``MEMOGRAPH_FRONTEND_URL=https://app.example.com``; we default
    to the same origin as the request when unset.
    """
    import os

    base = os.environ.get("MEMOGRAPH_FRONTEND_URL", "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    params: dict[str, str] = {}
    if source_id:
        params["connected"] = source_id
    if error:
        params["oauth_error"] = error
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"{base}/sources{query}")


__all__ = ["router"]
