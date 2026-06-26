"""Source-adapter management routes (Phase 1 of ADR 0002 v1.1+).

These routes expose :class:`memograph.sources.registry.SourceRegistry`
through the web API surface, behind the
``MEMOGRAPH_SOURCES_ENABLED=1`` feature flag.

Phase 1 supports the ``LOCAL`` source kind only. Subsequent phases
add S3 + Notion (Phase 2), GDrive (Phase 3), OneDrive (Phase 4) —
their POST handlers will branch in :func:`create_source` on the
``kind`` field. Until then, requests for non-LOCAL kinds 400 with a
clear "not implemented yet" message.

RBAC mirrors the existing admin tenants router:

* Read routes (``GET``) — any authenticated user
* Mutating routes (``POST`` / ``DELETE``) — ``admin`` scope

Every mutation writes one entry to ``_audit.log`` under the
tenant's ``.sources/`` directory via
:func:`memograph.sources.audit.record`.

Routes registered under ``/api/v1/sources``. Routing is in
:mod:`memograph.web.backend.server.create_app`; this module only
exposes ``router``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from memograph.sources import audit
from memograph.sources.base import (
    SourceConfig,
    SourceError,
    SourceHealth,
    SourceKind,
)
from memograph.sources.registry import (
    InvalidSourceIdError,
    SourceRegistry,
    validate_source_id,
)
from memograph.web.backend.auth import User, require_scope, require_user
from memograph.web.backend.observability import (
    record_source_health,
    record_source_swap,
)
from memograph.web.backend.tenant_resolver import resolve_tenant_id

logger = logging.getLogger("memograph.api.sources")

router = APIRouter(prefix="/sources", tags=["sources"])


# --- request / response models ---


class SourceParams(BaseModel):
    """Adapter-specific config. Validated by each adapter on register.

    Phase 1: LocalSource expects ``{"path": "/abs/path"}``.
    Phase 2+: each new kind adds its own fields. The Pydantic shape
    stays loose because the validation is adapter-side.
    """

    model_config = {"extra": "allow"}


class CreateSourceRequest(BaseModel):
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Stable id for this source within the tenant. "
            "Pattern: ^[a-z0-9_-]{1,64}$."
        ),
    )
    kind: SourceKind
    display_name: str = Field(..., min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)


class SourceResponse(BaseModel):
    source_id: str
    kind: SourceKind
    display_name: str
    tenant_id: str | None
    params: dict[str, Any]
    created_at: str
    is_active: bool

    @classmethod
    def from_config(
        cls, config: SourceConfig, active_source_id: str | None
    ) -> "SourceResponse":
        return cls(
            source_id=config.source_id,
            kind=config.kind,
            display_name=config.display_name,
            tenant_id=config.tenant_id,
            params=config.params,
            created_at=config.created_at.isoformat(),
            is_active=(config.source_id == active_source_id),
        )


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]
    active_source_id: str | None
    total: int


class SourceHealthResponse(BaseModel):
    source_id: str
    status: str
    checked_at: str
    last_successful_sync_at: str | None = None
    last_error: str | None = None
    documents_total: int | None = None

    @classmethod
    def from_health(
        cls, source_id: str, health: SourceHealth
    ) -> "SourceHealthResponse":
        return cls(
            source_id=source_id,
            status=health.status.value,
            checked_at=health.checked_at.isoformat(),
            last_successful_sync_at=(
                health.last_successful_sync_at.isoformat()
                if health.last_successful_sync_at
                else None
            ),
            last_error=health.last_error,
            documents_total=health.documents_total,
        )


class ActivateSourceResponse(BaseModel):
    tenant_id: str | None
    previous_active_source_id: str | None
    active_source_id: str


# --- helpers ---


def _registry(request: Request) -> SourceRegistry:
    """Return the registry or raise 503.

    The registry is built at startup when
    ``MEMOGRAPH_SOURCES_ENABLED=1``; missing means the operator
    hasn't opted in.
    """
    registry = getattr(request.app.state, "source_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "sources subsystem is disabled. "
                "Set MEMOGRAPH_SOURCES_ENABLED=1 to enable."
            ),
        )
    return registry


def _tenant_for(request: Request, user: User) -> str | None:
    """Return the calling tenant or None in single-tenant mode.

    Reuses :func:`resolve_tenant_id` for parity with other routes,
    but maps the synthetic ``SINGLE_TENANT_ID`` back to ``None`` so
    on-disk paths under the global root (``<root>/.sources/``) are
    used rather than ``<root>/default/.sources/``.
    """
    from memograph.web.backend.tenant_resolver import SINGLE_TENANT_ID

    registry_for_tenants = getattr(request.app.state, "tenant_registry", None)
    if registry_for_tenants is None:
        # Single-tenant: stash None so SourceRegistry uses
        # <global_root>/.sources/ directly.
        return None
    tid = resolve_tenant_id(request, user)
    return None if tid == SINGLE_TENANT_ID else tid


# --- routes ---


@router.get("", response_model=SourceListResponse)
async def list_sources(
    request: Request,
    user: User = Depends(require_user),
) -> SourceListResponse:
    """List every source configured for this tenant.

    Cheap: reads JSON configs from disk and the ``_active.json``
    marker. Does NOT warm any sources or probe health.
    """
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    configs = registry.list_configs(tenant_id)
    active = registry.get_active(tenant_id)
    return SourceListResponse(
        sources=[SourceResponse.from_config(c, active) for c in configs],
        active_source_id=active,
        total=len(configs),
    )


@router.get("/active", response_model=SourceResponse)
async def get_active_source(
    request: Request,
    user: User = Depends(require_user),
) -> SourceResponse:
    """Return the source the kernel is currently reading from.

    404 if no source has been activated yet — single-tenant
    deployments that haven't migrated yet are in this state.
    """
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    active = registry.get_active(tenant_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no active source set",
        )
    config = registry.get_config(tenant_id, active)
    if config is None:
        # Active marker points at a deleted config — inconsistent
        # state. Surface 500 so the operator notices; the GDPR
        # right-to-erasure path is meant to clear the marker too.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"active source {active!r} has no config on disk",
        )
    return SourceResponse.from_config(config, active)


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> SourceResponse:
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    config = registry.get_config(tenant_id, source_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source {source_id!r} not found",
        )
    return SourceResponse.from_config(config, registry.get_active(tenant_id))


@router.get("/{source_id}/health", response_model=SourceHealthResponse)
async def get_source_health(
    source_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> SourceHealthResponse:
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if registry.get_config(tenant_id, source_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source {source_id!r} not found",
        )
    source = registry.get(tenant_id, source_id)
    health = await source.health()
    # Surface to Prometheus too — the gauge is keyed by kind, so the
    # most recent health probe wins across multiple sources of the
    # same kind in the same tenant. That's acceptable for a coarse
    # gauge; per-source detail lives in this response.
    record_source_health(
        tenant_id=tenant_id,
        source_kind=source.kind.value,
        numeric_status=health.status.numeric(),
    )
    return SourceHealthResponse.from_health(source_id, health)


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    payload: CreateSourceRequest,
    request: Request,
    user: User = Depends(require_scope("admin")),
) -> SourceResponse:
    """Register a new source for the calling tenant.

    Phase 1: only ``LOCAL`` kind is supported. Other kinds return
    501 with a clear message pointing at the roadmap.
    """
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    try:
        validate_source_id(payload.source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if payload.kind is not SourceKind.LOCAL:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"source kind {payload.kind.value!r} is on the v1.1+ "
                "roadmap but not implemented in this build"
            ),
        )

    # LocalSource path validation: must be absolute, must not contain
    # ".." segments, must not resolve outside its declared root.
    # VaultStorage will create the directory if missing — that's the
    # intended UX for "I picked a new folder" registration.
    path_raw = payload.params.get("path")
    if not path_raw or not isinstance(path_raw, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source requires params['path'] (absolute path)",
        )
    p = Path(path_raw).expanduser()
    if not p.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source path must be absolute",
        )
    # Reject paths whose unresolved form contains ".." — defense in
    # depth even though VaultStorage's own guards apply later.
    if any(part == ".." for part in p.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source path must not contain '..' segments",
        )

    config = SourceConfig(
        source_id=payload.source_id,
        kind=payload.kind,
        display_name=payload.display_name,
        tenant_id=tenant_id,
        params={"path": str(p)},
    )
    try:
        registry.register(config)
    except SourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    audit.record(
        sources_dir=registry._sources_dir(tenant_id),
        action=audit.ACTION_CREATE,
        source_id=config.source_id,
        source_kind=config.kind.value,
        user_id=user.id,
        tenant_id=tenant_id,
        request_id=getattr(request.state, "request_id", None),
        after={
            "display_name": config.display_name,
            "params": config.params,
        },
    )

    return SourceResponse.from_config(config, registry.get_active(tenant_id))


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    source_id: str,
    request: Request,
    user: User = Depends(require_scope("admin")),
) -> None:
    """Remove a source. Idempotent.

    Does NOT delete data at the source itself (compliance/GDPR
    decision documented in ADR 0002 + the GDPR runbook). For LocalSource,
    the actual ``.md`` files on disk are preserved; the operator can
    re-register the same path later.
    """
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    config = registry.get_config(tenant_id, source_id)
    removed = registry.delete(tenant_id, source_id)
    if not removed:
        # 204 either way — DELETE is idempotent — but skip the
        # audit entry if there was nothing to delete.
        return None

    audit.record(
        sources_dir=registry._sources_dir(tenant_id),
        action=audit.ACTION_DELETE,
        source_id=source_id,
        source_kind=config.kind.value if config else "unknown",
        user_id=user.id,
        tenant_id=tenant_id,
        request_id=getattr(request.state, "request_id", None),
        before=(
            {
                "display_name": config.display_name,
                "params": config.params,
            }
            if config
            else None
        ),
    )
    return None


@router.post(
    "/{source_id}/activate",
    response_model=ActivateSourceResponse,
)
async def activate_source(
    source_id: str,
    request: Request,
    user: User = Depends(require_scope("admin")),
) -> ActivateSourceResponse:
    """Set the active source — the one the kernel reads from.

    Phase 1 ships a synchronous swap: the marker file is updated,
    the audit entry is written, and the response returns immediately.
    Phase 5 will add multi-worker swap coordination through Redis
    pub/sub; the route signature does not change.
    """
    registry = _registry(request)
    tenant_id = _tenant_for(request, user)
    try:
        validate_source_id(source_id)
    except InvalidSourceIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    config = registry.get_config(tenant_id, source_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source {source_id!r} not found",
        )

    previous = registry.get_active(tenant_id)
    previous_config = (
        registry.get_config(tenant_id, previous) if previous else None
    )

    try:
        registry.set_active(tenant_id, source_id)
    except SourceError as exc:
        record_source_swap(
            tenant_id=tenant_id,
            from_kind=previous_config.kind.value if previous_config else None,
            to_kind=config.kind.value,
            result="failed",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    record_source_swap(
        tenant_id=tenant_id,
        from_kind=previous_config.kind.value if previous_config else None,
        to_kind=config.kind.value,
        result="ok",
    )

    audit.record(
        sources_dir=registry._sources_dir(tenant_id),
        action=audit.ACTION_ACTIVATE,
        source_id=source_id,
        source_kind=config.kind.value,
        user_id=user.id,
        tenant_id=tenant_id,
        request_id=getattr(request.state, "request_id", None),
        before={"source_id": previous} if previous else None,
        after={"source_id": source_id},
    )

    return ActivateSourceResponse(
        tenant_id=tenant_id,
        previous_active_source_id=previous,
        active_source_id=source_id,
    )


__all__ = ["router"]
