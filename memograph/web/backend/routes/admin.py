"""Admin routes for tenant lifecycle (Phase 3.4).

These are *the only* routes that can name a ``tenant_id`` other than
the caller's own. All routes require the ``admin`` scope (granted via
the auth provider's role/scope claim, not configurable from a request).

The routes are intentionally thin — they delegate every operation to
:class:`memograph.core.tenant_registry.TenantRegistry`, which holds
the isolation invariants. Phase 3.6 will add quota enforcement to
the create path; Phase 3.7 will replace the eager
:func:`offboard_tenant` with a scheduled-deletion runbook.

The registry is stored on ``request.app.state.tenant_registry`` and
populated at startup when ``MEMOGRAPH_TENANCY_ENABLED=1`` is set.
When tenancy is disabled (the default during the v0.x → v1.0
transition), these routes return 503 — they cannot service requests
without a registry.

Tests for this router live in ``tests/tenancy/test_admin_routes.py``.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from memograph.core.tenant_registry import TenantRegistry
from memograph.storage.tenant_storage import InvalidTenantIdError

logger = logging.getLogger("memograph.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="New tenant id (lowercase alnum + dash + underscore).",
    )


class TenantInfo(BaseModel):
    tenant_id: str
    warm: bool
    usage_bytes: int


class TenantListResponse(BaseModel):
    tenants: list[TenantInfo]
    total: int
    warm: int


def _registry(request: Request) -> TenantRegistry:
    """Return the registry or raise 503.

    Routes use this rather than depending on the registry directly so
    a missing registry produces a clean error instead of an
    ``AttributeError`` from FastAPI's dependency resolver.
    """
    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="multi-tenancy is not enabled on this deployment",
        )
    return cast(TenantRegistry, registry)


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(request: Request) -> TenantListResponse:
    """List every tenant on disk plus warm-cache state and on-disk
    usage."""
    registry = _registry(request)
    warm = set(registry.warm_tenants())
    known = registry.known_tenants()
    items = [
        TenantInfo(
            tenant_id=tid,
            warm=(tid in warm),
            usage_bytes=registry.usage_bytes(tid),
        )
        for tid in known
    ]
    return TenantListResponse(
        tenants=items,
        total=len(items),
        warm=len(warm),
    )


@router.post(
    "/tenants",
    response_model=TenantInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(payload: TenantCreateRequest, request: Request) -> TenantInfo:
    """Create a tenant directory and warm a kernel for it.

    Idempotent: if the tenant already exists, the directory is left
    in place. The response always reflects the post-call state.
    """
    registry = _registry(request)
    try:
        registry.for_tenant(payload.tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return TenantInfo(
        tenant_id=payload.tenant_id,
        warm=True,
        usage_bytes=registry.usage_bytes(payload.tenant_id),
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantInfo,
)
async def get_tenant(tenant_id: str, request: Request) -> TenantInfo:
    """Return tenant metadata. 404s if the tenant has no directory
    on disk."""
    registry = _registry(request)
    try:
        # Validate id by passing through the registry; reject without
        # leaking validation details beyond a 400.
        from memograph.storage.tenant_storage import validate_tenant_id

        validate_tenant_id(tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if tenant_id not in registry.known_tenants():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant {tenant_id!r} not found",
        )
    return TenantInfo(
        tenant_id=tenant_id,
        warm=tenant_id in registry.warm_tenants(),
        usage_bytes=registry.usage_bytes(tenant_id),
    )


@router.delete(
    "/tenants/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def offboard_tenant(tenant_id: str, request: Request) -> None:
    """Hard-delete a tenant.

    **This is destructive and immediate.** Phase 3.7 will replace
    this with a scheduled deletion that takes a final tarball
    snapshot and waits for a grace period before purging. For now the
    semantics match the underlying primitive in
    :class:`TenantStorage`.

    Returns 204 if anything was deleted; 404 if the tenant didn't
    exist (warm or on disk).
    """
    registry = _registry(request)
    try:
        from memograph.storage.tenant_storage import validate_tenant_id

        validate_tenant_id(tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    removed = registry.offboard(tenant_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant {tenant_id!r} not found",
        )
    logger.info("offboarded tenant %s", tenant_id)


@router.get(
    "/tenants/{tenant_id}/usage",
    response_model=TenantInfo,
)
async def tenant_usage(tenant_id: str, request: Request) -> TenantInfo:
    """Tenant on-disk usage. Returns 0 bytes for an unknown tenant
    rather than 404 — useful for billing pipelines that want a
    uniform shape across known and recently-offboarded tenants.
    """
    registry = _registry(request)
    try:
        from memograph.storage.tenant_storage import validate_tenant_id

        validate_tenant_id(tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return TenantInfo(
        tenant_id=tenant_id,
        warm=tenant_id in registry.warm_tenants(),
        usage_bytes=registry.usage_bytes(tenant_id),
    )
