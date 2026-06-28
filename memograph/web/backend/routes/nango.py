"""Routes for the Nango-backed cloud source flow.

Replaces the previous bespoke ``/oauth/google/*`` + ``/oauth/microsoft/*``
endpoints. Three routes:

* ``POST /api/v1/sources/connect-session`` — admin-scoped. Mints a
  short-lived Nango Connect session token tagged with the calling
  tenant + the source's MemoGraph metadata. Frontend hands the token
  to ``@nangohq/frontend.openConnectUI()``.

* ``POST /api/v1/sources/webhook`` — public, HMAC-verified. Receives
  Nango's ``auth/connection.creation`` events and registers the new
  source in the registry. Idempotent: re-delivery of the same event
  overwrites the config (no duplicate sources are created).

* ``GET /api/v1/sources/nango/health`` — admin-scoped. Surfaces
  whether Nango is reachable from this process; useful diagnostic
  for the frontend to gate the wizard's cloud-kind buttons.

Nango handles every other OAuth concern (the PKCE dance, scopes,
encrypted refresh-token storage, automatic refresh, provider quirks).
This module is intentionally thin.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from memograph.sources import audit
from memograph.sources.base import (
    SourceConfig,
    SourceError,
    SourceKind,
)
from memograph.sources.nango_client import (
    PROVIDER_KEY_TO_KIND,
    NangoClient,
    NangoConfigError,
)
from memograph.sources.registry import (
    InvalidSourceIdError,
    SourceRegistry,
    validate_source_id,
)
from memograph.web.backend.auth import User, require_scope, require_user
from memograph.web.backend.tenant_resolver import (
    SINGLE_TENANT_ID,
    resolve_tenant_id,
)

logger = logging.getLogger("memograph.api.nango")

router = APIRouter(tags=["sources"])


# --- request / response models -------------------------------------------


class ConnectSessionRequest(BaseModel):
    kind: SourceKind
    display_name: str | None = Field(default=None, max_length=128)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)


class ConnectSessionResponse(BaseModel):
    session_token: str
    expires_at: str
    source_id: str
    connect_link: str | None = None


class NangoHealthResponse(BaseModel):
    configured: bool
    base_url: str | None = None
    public_url: str | None = None
    # Provider-config-keys ("unique_key") of integrations the operator
    # has configured in the Nango admin UI. The wizard greys out
    # cloud-kind buttons that aren't in this list so users don't click
    # through to a Connect modal that fails inside Nango.
    available_integrations: list[str] = Field(default_factory=list)
    last_error: str | None = None


# --- helpers --------------------------------------------------------------


def _registry(request: Request) -> SourceRegistry:
    registry = getattr(request.app.state, "source_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "sources subsystem is disabled. "
                "Unset MEMOGRAPH_SOURCES_ENABLED (or set =1) to enable."
            ),
        )
    return registry


def _nango_client(request: Request) -> NangoClient:
    client = getattr(request.app.state, "nango_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Nango is not configured. Set MEMOGRAPH_NANGO_BASE_URL + "
                "MEMOGRAPH_NANGO_SECRET_KEY and restart the server."
            ),
        )
    return client


def _tenant_for(request: Request, user: User) -> str | None:
    """Mirror of the helper in routes/sources.py."""
    registry_for_tenants = getattr(request.app.state, "tenant_registry", None)
    if registry_for_tenants is None:
        return None
    tid = resolve_tenant_id(request, user)
    return None if tid == SINGLE_TENANT_ID else tid


def _auto_source_id(kind: SourceKind) -> str:
    """Generate a short, URL-safe source_id like ``gdrive-a1b2c3``."""
    return f"{kind.value}-{secrets.token_hex(3)}"


# --- routes ---------------------------------------------------------------


@router.post(
    "/sources/connect-session",
    response_model=ConnectSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connect_session(
    payload: ConnectSessionRequest,
    request: Request,
    user: User = Depends(require_scope("admin")),
) -> ConnectSessionResponse:
    """Begin a Nango Connect flow for an OAuth cloud source.

    Returns the session token the frontend hands to Nango Connect.
    After the user signs in, Nango POSTs the connection-creation
    webhook to ``/sources/webhook`` which registers the resulting
    source. We never see access tokens.
    """
    if payload.kind not in PROVIDER_KEY_TO_KIND.values():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"kind {payload.kind.value!r} is not routed through Nango; "
                "use POST /sources for local / s3 sources"
            ),
        )

    source_id = payload.source_id or _auto_source_id(payload.kind)
    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    tenant_id = _tenant_for(request, user)
    # Ensure registry is wired (so the webhook can land successfully).
    _registry(request)
    client = _nango_client(request)

    try:
        session = await client.create_connect_session(
            kind=payload.kind,
            tenant_id=tenant_id,
            source_id=source_id,
            end_user_id=user.id,
            end_user_email=user.email,
            display_name=payload.display_name,
        )
    except NangoConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return ConnectSessionResponse(
        session_token=session.token,
        expires_at=session.expires_at.isoformat(),
        source_id=source_id,
        connect_link=session.connect_link,
    )


@router.post(
    "/sources/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def nango_webhook(request: Request) -> None:
    """Receive Nango connection-creation / refresh-failure events.

    HMAC-verified against ``MEMOGRAPH_NANGO_WEBHOOK_SECRET``. Idempotent
    by design — the registry overwrites a config on re-delivery, and
    the audit log captures every event.

    Public route (no Bearer token). Nango authenticates itself via the
    signature header; we never trust the body fields beyond what the
    signature covers.
    """
    client = _nango_client(request)
    raw_body = await request.body()
    signature = request.headers.get("x-nango-signature")
    if not client.verify_webhook_signature(raw_body=raw_body, signature=signature):
        logger.warning(
            "rejecting Nango webhook with bad/missing signature " "(content_length=%d)",
            len(raw_body),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook signature",
        )

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"webhook body is not valid JSON: {exc}",
        ) from exc

    # Nango sends type=auth for connection lifecycle events.
    if payload.get("type") != "auth":
        # Other event types (e.g. sync, action) are not actionable here
        # but acknowledging with 204 keeps Nango from retrying. The
        # audit entry records that we saw something.
        logger.info("ignoring non-auth Nango webhook type=%r", payload.get("type"))
        return None

    if not payload.get("success", False):
        # Connection creation failed (user cancelled, provider rejected,
        # etc.). Log it; nothing to register.
        logger.info(
            "Nango auth webhook reports failure: %s",
            payload.get("operation"),
        )
        return None

    operation = payload.get("operation")
    connection_id = payload.get("connectionId") or payload.get("connection_id")
    provider_config_key = payload.get("providerConfigKey") or payload.get(
        "provider_config_key"
    )
    tags = payload.get("tags") or payload.get("metadata") or {}

    if not isinstance(connection_id, str) or not isinstance(provider_config_key, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "webhook missing connectionId/providerConfigKey; cannot "
                "match the new connection to a MemoGraph source"
            ),
        )

    kind = PROVIDER_KEY_TO_KIND.get(provider_config_key)
    if kind is None:
        # Operator added a Nango integration we don't model. Accept
        # the webhook (204) but skip registration so we don't error
        # the user's flow; surface in logs for triage.
        logger.warning(
            "Nango webhook for unsupported provider_config_key=%r; ignoring",
            provider_config_key,
        )
        return None

    # Re-key tags onto our internal fields.
    source_id = _coerce_tag(tags, "memograph_source_id") or _auto_source_id(kind)
    tenant_id = _coerce_tag(tags, "memograph_tenant_id")
    display_name = _coerce_tag(tags, "memograph_display_name") or _default_display_name(
        kind
    )

    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"webhook tagged invalid source_id {source_id!r}: {exc}",
        ) from exc

    registry = _registry(request)
    config = SourceConfig(
        source_id=source_id,
        kind=kind,
        display_name=display_name,
        tenant_id=tenant_id,
        params={"nango_connection_id": connection_id},
    )
    try:
        registry.register(config)
    except SourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to register Nango-backed source: {exc}",
        ) from exc

    audit.record(
        sources_dir=registry._sources_dir(tenant_id),
        action=audit.ACTION_OAUTH_EXCHANGE,
        source_id=source_id,
        source_kind=kind.value,
        user_id=_coerce_tag(tags, "end_user_id") or "unknown",
        tenant_id=tenant_id,
        request_id=getattr(request.state, "request_id", None),
        after={
            "operation": operation,
            "nango_connection_id": connection_id,
        },
    )
    logger.info(
        "registered Nango source tenant=%s source_id=%s kind=%s connection_id=%s",
        tenant_id,
        source_id,
        kind.value,
        connection_id,
    )

    # First-source auto-activate: same UX commitment as the local
    # POST /sources path — the user shouldn't have to click Activate
    # after completing OAuth for their first cloud source.
    if registry.get_active(tenant_id) is None:
        try:
            registry.set_active(tenant_id, source_id)
        except SourceError as exc:
            logger.warning(
                "auto-activate failed for %s/%s: %s",
                tenant_id,
                source_id,
                exc,
            )
        else:
            from memograph.sources.kernel_binding import swap_kernel_to_source

            await swap_kernel_to_source(request.app, tenant_id, source_id)

    return None


@router.get(
    "/nango/health",
    response_model=NangoHealthResponse,
)
async def nango_health(
    request: Request,
    user: User = Depends(require_user),
) -> NangoHealthResponse:
    """Lightweight probe: is Nango configured + the secret valid?

    Used by the wizard to decide whether to show the cloud-kind
    buttons or render a "configure Nango first" message instead.
    """
    client = getattr(request.app.state, "nango_client", None)
    if client is None:
        return NangoHealthResponse(
            configured=False,
            last_error=(
                "Nango is not configured. Set MEMOGRAPH_NANGO_BASE_URL + "
                "MEMOGRAPH_NANGO_SECRET_KEY and restart."
            ),
        )
    # Probe with /integrations (cheap, side-effect-free) instead of
    # minting a session against a sentinel id. The previous probe
    # accumulated orphan sessions in Nango's storage.
    try:
        integrations = await client.list_integrations()
    except NangoConfigError as exc:
        return NangoHealthResponse(
            configured=True,
            base_url=client.config.base_url,
            public_url=client.config.public_url,
            last_error=str(exc),
        )
    except SourceError as exc:
        return NangoHealthResponse(
            configured=True,
            base_url=client.config.base_url,
            public_url=client.config.public_url,
            last_error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return NangoHealthResponse(
            configured=True,
            base_url=client.config.base_url,
            public_url=client.config.public_url,
            last_error=str(exc),
        )
    keys: list[str] = []
    for item in integrations:
        key = item.get("unique_key") if isinstance(item, dict) else None
        if isinstance(key, str) and key:
            keys.append(key)
    return NangoHealthResponse(
        configured=True,
        base_url=client.config.base_url,
        public_url=client.config.public_url,
        available_integrations=keys,
    )


# --- helpers --------------------------------------------------------------


def _coerce_tag(tags: Any, key: str) -> str | None:
    if not isinstance(tags, dict):
        return None
    value = tags.get(key)
    return value if isinstance(value, str) and value else None


def _default_display_name(kind: SourceKind) -> str:
    return {
        SourceKind.GDRIVE: "Google Drive",
        SourceKind.ONEDRIVE: "OneDrive",
        SourceKind.NOTION: "Notion",
    }.get(kind, kind.value)


__all__ = ["router"]
