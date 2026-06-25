"""Admin routes for tenant lifecycle (Phases 3.4 + 3.7).

These are *the only* routes that can name a ``tenant_id`` other than
the caller's own. All routes require the ``admin`` scope (granted via
the auth provider's role/scope claim, not configurable from a request).

Two destructive paths exist for tenant offboarding:

* ``DELETE /tenants/{id}`` — immediate, irreversible. Use only when
  the operator has already taken a final backup; this is the original
  Phase 3.4 primitive and is preserved for emergency cases.
* ``POST /tenants/{id}/schedule-delete`` — Phase 3.7 GDPR runbook
  flow. Writes a tombstone with a configurable grace period (default
  7 days). The reaper script (``memograph.scripts.run_reaper``)
  destroys the tenant once the grace period expires; the operator
  can cancel beforehand via ``DELETE /tenants/{id}/schedule-delete``.

While a tenant is tombstoned, non-admin requests resolve to **410
Gone** (see :mod:`memograph.web.backend.tenant_resolver`); admin
routes still serve so the operator can inspect or cancel.

The registry is stored on ``request.app.state.tenant_registry`` and
populated at startup when ``MEMOGRAPH_TENANCY_ENABLED=1`` is set.
When tenancy is disabled (the default during the v0.x → v1.0
transition), these routes return 503 — they cannot service requests
without a registry.

Tests for this router live in ``tests/tenancy/test_admin_routes.py``
and ``tests/tenancy/test_scheduled_deletion.py``.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from memograph.core.tenant_registry import TenantRegistry
from memograph.storage.tenant_storage import (
    InvalidTenantIdError,
    validate_tenant_id,
)
from memograph.storage.tombstone import (
    DEFAULT_GRACE_DAYS,
    TombstoneError,
    clear_tombstone,
    is_tombstoned,
    read_tombstone,
    write_tombstone,
)
from memograph.web.backend.auth import User, require_user

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
    # Phase 3.7: present only when the tenant is tombstoned. Clients
    # can hide / red-flag the tenant in their UI based on these.
    tombstoned: bool = False
    tombstone_scheduled_at: str | None = None
    tombstone_delete_after: str | None = None


class TenantListResponse(BaseModel):
    tenants: list[TenantInfo]
    total: int
    warm: int


class ScheduleDeleteRequest(BaseModel):
    grace_days: int = Field(
        DEFAULT_GRACE_DAYS,
        ge=0,
        le=365,
        description=(
            "Number of days before the reaper destroys the tenant. "
            "0 = destroy at the next reaper run. Default 7."
        ),
    )
    reason: str = Field(
        "",
        max_length=500,
        description="Free-text reason recorded on the tombstone for audit.",
    )


class ScheduleDeleteResponse(BaseModel):
    tenant_id: str
    scheduled_at: str
    delete_after: str
    requested_by: str
    reason: str


def _tenant_info(registry: TenantRegistry, tenant_id: str) -> TenantInfo:
    """Build a :class:`TenantInfo` with tombstone fields if present.

    Reading the tombstone is best-effort — if the file is corrupted
    we still return the tenant rather than 500ing the whole list.
    Operators investigating a corrupted tombstone go through the
    reaper diagnostic path (``run_reaper --dry-run``).
    """
    info = TenantInfo(
        tenant_id=tenant_id,
        warm=tenant_id in registry.warm_tenants(),
        usage_bytes=registry.usage_bytes(tenant_id),
    )
    tenant_dir = registry.storage.tenant_path(tenant_id)
    try:
        tombstone = read_tombstone(tenant_dir)
    except TombstoneError as exc:
        logger.warning("tenant %s has a malformed tombstone: %s", tenant_id, exc)
        return info.model_copy(update={"tombstoned": True})
    if tombstone is None:
        return info
    return info.model_copy(
        update={
            "tombstoned": True,
            "tombstone_scheduled_at": tombstone.scheduled_at,
            "tombstone_delete_after": tombstone.delete_after,
        }
    )


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
    """List every tenant on disk plus warm-cache state, on-disk
    usage, and tombstone status."""
    registry = _registry(request)
    warm = set(registry.warm_tenants())
    known = registry.known_tenants()
    items = [_tenant_info(registry, tid) for tid in known]
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

    Refuses to (re-)warm a tombstoned tenant — the operator must
    cancel the scheduled deletion first via
    ``DELETE /tenants/{id}/schedule-delete``.
    """
    registry = _registry(request)
    try:
        validate_tenant_id(payload.tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    tenant_dir = registry.storage.tenant_path(payload.tenant_id)
    if is_tombstoned(tenant_dir):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "tenant is scheduled for deletion; cancel the "
                "tombstone before re-warming"
            ),
        )
    try:
        registry.for_tenant(payload.tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _tenant_info(registry, payload.tenant_id)


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantInfo,
)
async def get_tenant(tenant_id: str, request: Request) -> TenantInfo:
    """Return tenant metadata including tombstone state. 404s if the
    tenant has no directory on disk."""
    registry = _registry(request)
    try:
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
    return _tenant_info(registry, tenant_id)


@router.delete(
    "/tenants/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def offboard_tenant(tenant_id: str, request: Request) -> None:
    """Immediate, irreversible hard-delete.

    **Destructive.** For the standard GDPR offboarding flow, prefer
    ``POST /tenants/{id}/schedule-delete`` (Phase 3.7) which writes
    a tombstone, takes a final backup, and lets the reaper destroy
    the tenant after a configurable grace period.

    This route is preserved for emergency cases where the operator
    has already taken a final backup out-of-band and accepts the
    irreversible nature of the delete.

    Returns 204 if anything was deleted; 404 if the tenant didn't
    exist (warm or on disk).
    """
    registry = _registry(request)
    try:
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
    logger.info("offboarded tenant %s (immediate)", tenant_id)


@router.post(
    "/tenants/{tenant_id}/schedule-delete",
    response_model=ScheduleDeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def schedule_delete_tenant(
    tenant_id: str,
    payload: ScheduleDeleteRequest,
    request: Request,
    user: User = Depends(require_user),
) -> ScheduleDeleteResponse:
    """Schedule a tenant for deletion (Phase 3.7).

    Writes a tombstone with a configurable grace period. While the
    tombstone is in place, non-admin requests for the tenant return
    410 Gone. The reaper script
    (``python -m memograph.scripts.run_reaper <global_root>``)
    destroys tenants whose grace period has expired.

    Cancel before the grace expires via
    ``DELETE /tenants/{id}/schedule-delete``.
    """
    registry = _registry(request)
    try:
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
    tenant_dir = registry.storage.tenant_path(tenant_id)
    try:
        tombstone = write_tombstone(
            tenant_dir,
            requested_by=user.id,
            grace_days=payload.grace_days,
            reason=payload.reason,
        )
    except TombstoneError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    logger.info(
        "scheduled tenant %s for deletion: grace=%d days, by=%s",
        tenant_id,
        payload.grace_days,
        user.id,
    )
    return ScheduleDeleteResponse(
        tenant_id=tenant_id,
        scheduled_at=tombstone.scheduled_at,
        delete_after=tombstone.delete_after,
        requested_by=tombstone.requested_by,
        reason=tombstone.reason,
    )


@router.delete(
    "/tenants/{tenant_id}/schedule-delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scheduled_delete(tenant_id: str, request: Request) -> None:
    """Cancel a scheduled deletion before the reaper fires.

    404 if no tombstone is present (the tenant was either never
    scheduled or already destroyed).
    """
    registry = _registry(request)
    try:
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
    tenant_dir = registry.storage.tenant_path(tenant_id)
    cleared = clear_tombstone(tenant_dir)
    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tenant {tenant_id!r} is not scheduled for deletion",
        )
    logger.info("cancelled scheduled deletion of tenant %s", tenant_id)


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
        validate_tenant_id(tenant_id)
    except InvalidTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _tenant_info(registry, tenant_id)
