"""Per-request tenant resolution for the FastAPI surface (Phase 3.5).

Until this module landed, every web route reached into
``request.app.state.kernel`` and got the single-process kernel.
Multi-tenancy was opt-in only at the admin-router layer; non-admin
routes had no tenant scoping.

This module flips that. The :func:`kernel_for_request` dependency:

1. Reads :class:`User` from auth context.
2. Resolves a tenant id (single-tenant mode → ``"default"``,
   multi-tenant mode → ``user.organization_id`` or **403**).
3. Returns the right :class:`MemoryKernel` instance — either
   ``app.state.kernel`` (single-tenant) or
   ``registry.for_tenant(tid)`` (multi-tenant).

Routes that depended on ``request.app.state.kernel`` switch to
``kernel: MemoryKernel = Depends(kernel_for_request)``. The change
is mechanical; behaviour is unchanged when tenancy is disabled
(backwards-compat with single-tenant deployments).

Audit-log integration: the existing :func:`current_user`
``ContextVar`` already carries ``organization_id``, which
``action_logger._identity_from_context()`` reads as ``tenant_id``.
We don't need a separate tenant ContextVar; populating
``User.organization_id`` correctly during auth is enough.
"""

from __future__ import annotations

from typing import cast

from fastapi import Depends, HTTPException, Request, status

from memograph.core.kernel import MemoryKernel
from memograph.web.backend.auth import User, require_user


SINGLE_TENANT_ID = "default"
"""Synthetic tenant id used in single-tenant mode. Matches the
migration target documented in ADR 0001 (existing single-vault
deployments map onto ``<global_root>/default/``)."""


def resolve_tenant_id(request: Request, user: User) -> str:
    """Pick the tenant id for the calling user.

    Three branches, in order:

    * Tenancy disabled (``app.state.tenant_registry`` is ``None``):
      always returns ``SINGLE_TENANT_ID``. The caller's
      ``organization_id`` is ignored — single-tenant mode predates
      tenant claims and we don't want to break local-dev flows by
      requiring one.
    * Tenancy enabled, ``user.organization_id`` set: that's the
      tenant.
    * Tenancy enabled, no organization_id (e.g. an API key without
      a tenant binding, or an OIDC token that didn't project the
      claim): **403**. The auth was valid but the caller has no
      tenant assignment.
    """
    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        return SINGLE_TENANT_ID

    tid = (user.organization_id or "").strip()
    if not tid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="authenticated but no tenant claim",
        )
    return tid


def kernel_for_request(
    request: Request,
    user: User = Depends(require_user),
) -> MemoryKernel:
    """FastAPI dependency: returns the right kernel for this request.

    Stashes ``tenant_id`` on ``request.state`` so middlewares and
    log formatters that want to attach it as a label can read it
    without re-running the resolver.

    Single-tenant fallback: if no registry is configured, returns
    ``request.app.state.kernel`` unchanged. If neither a registry
    nor a single-tenant kernel exists, raises **503** — the server
    is not yet ready to serve requests (likely a startup race).
    """
    tid = resolve_tenant_id(request, user)
    request.state.tenant_id = tid

    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is not None:
        return cast(MemoryKernel, registry.for_tenant(tid))

    kernel = getattr(request.app.state, "kernel", None)
    if kernel is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="kernel not initialized",
        )
    return cast(MemoryKernel, kernel)


__all__ = [
    "SINGLE_TENANT_ID",
    "kernel_for_request",
    "resolve_tenant_id",
]
