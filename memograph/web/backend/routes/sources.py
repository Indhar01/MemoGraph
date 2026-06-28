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


class SyncSourceResponse(BaseModel):
    source_id: str
    in_flight: bool
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


# --- helpers ---


def _registry(request: Request) -> SourceRegistry:
    """Return the registry or raise 503.

    The registry is built at startup by default; missing means the
    operator explicitly opted out with ``MEMOGRAPH_SOURCES_ENABLED=0``.
    """
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


def _validate_local_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate + canonicalise LocalSource params.

    Raises ``HTTPException(400)`` on any failure. Returns the
    cleaned params dict; callers pass this straight into
    :class:`SourceConfig.params`.

    The existence check happens here (at registration) rather than
    only on the first health probe. Wizard users expect "I typed a
    bad path → I get told now"; a 201 followed by a red health pill
    is a worse experience than a 400 with a clear message.
    """
    path_raw = params.get("path")
    if not path_raw or not isinstance(path_raw, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source requires params['path'] (absolute path)",
        )
    # Trim whitespace + strip wrapping quotes that copy-paste from a
    # terminal often introduces ("/path/with spaces" → /path/with spaces).
    cleaned_raw = path_raw.strip().strip('"').strip("'")
    if not cleaned_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source path is empty after trimming",
        )
    try:
        p = Path(cleaned_raw).expanduser()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LOCAL source path is not a valid path: {exc}",
        ) from exc
    if not p.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"LOCAL source path must be absolute (got {cleaned_raw!r}). "
                "On Windows, include the drive letter, e.g. C:/Users/me/notes."
            ),
        )
    if any(part == ".." for part in p.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOCAL source path must not contain '..' segments",
        )
    # Resolve once so we store a canonical absolute path and so the
    # existence check below sees what the adapter will actually use.
    try:
        resolved = p.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LOCAL source path could not be resolved: {exc}",
        ) from exc
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"LOCAL source path does not exist on this server: "
                f"{resolved}. (You entered {path_raw!r}.) If you're "
                "running MemoGraph in Docker, the path must exist "
                "*inside the container* — bind-mount your host folder."
            ),
        )
    if not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"LOCAL source path is not a directory: {resolved}. "
                "Point at the folder containing your .md files, "
                "not at a single file."
            ),
        )
    return {"path": str(resolved)}


def _validate_s3_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate S3 params: ``bucket`` required, everything else optional.

    Credentials, when present, are stored as-is on disk in the
    JSON config. Operators should prefer the ambient AWS credential
    chain (env, profile, instance role) and leave the credential
    fields unset in the request body.
    """
    bucket = params.get("bucket")
    if not bucket or not isinstance(bucket, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3 source requires params['bucket']",
        )
    # Pass through only the recognized fields so a typo in the
    # request body doesn't quietly persist.
    cleaned: dict[str, Any] = {"bucket": bucket}
    for k in (
        "prefix",
        "region",
        "endpoint_url",
        "access_key_id",
        "secret_access_key",
        "session_token",
        "suffix",
    ):
        if k in params and params[k] is not None:
            cleaned[k] = params[k]
    return cleaned


def _validate_notion_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate Notion params for the scripted-creation path.

    Notion sources are normally created through the Nango Connect
    flow, which writes ``nango_connection_id`` into the params via
    the webhook handler. Scripted callers can still POST a Notion
    source directly if they pre-create the Nango connection — they
    must supply ``nango_connection_id`` explicitly.
    """
    cleaned: dict[str, Any] = {}
    nango_connection_id = params.get("nango_connection_id")
    if not nango_connection_id or not isinstance(nango_connection_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "NOTION source requires params['nango_connection_id']. "
                "Use POST /api/v1/sources/connect-session for the "
                "wizard flow; scripted callers must mint the Nango "
                "connection first."
            ),
        )
    cleaned["nango_connection_id"] = nango_connection_id
    for k in ("database_id", "filter_query"):
        if k in params and params[k]:
            cleaned[k] = params[k]
    return cleaned


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

    # Per-kind param validation. LOCAL + S3 + NOTION can be created
    # directly via this route. GDRIVE + ONEDRIVE go through the Nango
    # Connect flow (POST /sources/connect-session) which writes the
    # SourceConfig from the webhook handler — accepting them here
    # would silently create unusable entries.
    if payload.kind is SourceKind.LOCAL:
        validated_params = _validate_local_params(payload.params)
    elif payload.kind is SourceKind.S3:
        validated_params = _validate_s3_params(payload.params)
    elif payload.kind is SourceKind.NOTION:
        # Notion also runs over Nango but a scripted caller who
        # already has a Nango connection_id can register directly by
        # supplying it. The validator enforces the field.
        validated_params = _validate_notion_params(payload.params)
    elif payload.kind in (SourceKind.GDRIVE, SourceKind.ONEDRIVE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{payload.kind.value!r} sources cannot be created via "
                "POST /sources — use POST /sources/connect-session "
                "to start the Nango Connect flow instead. The webhook "
                "registers the source automatically on success."
            ),
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported source kind {payload.kind.value!r}",
        )

    config = SourceConfig(
        source_id=payload.source_id,
        kind=payload.kind,
        display_name=payload.display_name,
        tenant_id=tenant_id,
        params=validated_params,
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

    # First-source auto-activate: if the tenant has no active source
    # yet, mark this one active and point the kernel at it. Without
    # this the user has to click Activate manually after Add, which
    # was the exact UX trap we just fixed.
    if registry.get_active(tenant_id) is None:
        try:
            registry.set_active(tenant_id, config.source_id)
        except SourceError as exc:
            logger.warning(
                "auto-activate failed for %s/%s: %s",
                tenant_id,
                config.source_id,
                exc,
            )
        else:
            from memograph.sources.kernel_binding import swap_kernel_to_source

            await swap_kernel_to_source(request.app, tenant_id, config.source_id)

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

    The marker file is written atomically, the swap event is
    published through the :class:`SwapCoordinator` (a no-op in
    single-worker installs; a Redis pub/sub message otherwise), and
    the audit entry is appended before the route returns. Peer
    workers process the event asynchronously and invalidate their
    cached active-source decision; convergence is sub-second on a
    healthy Redis.
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

    # Multi-worker propagation. The coordinator is always present in
    # single-process mode too (as a NullSwapCoordinator no-op), so
    # this call is unconditional. Failure to publish is surfaced to
    # the caller — a swap that lands on disk but doesn't propagate is
    # worse than a 500 that prompts a retry.
    coordinator = getattr(request.app.state, "swap_coordinator", None)
    if coordinator is not None:
        try:
            await coordinator.publish_swap(tenant_id, source_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "swap publish failed (tenant=%s source_id=%s): %s",
                tenant_id,
                source_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "source activated locally but could not publish "
                    "the swap event to peer workers; check the swap "
                    "coordinator (e.g. Redis connectivity)"
                ),
            ) from exc

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

    # Re-point the kernel at the newly active source and trigger a
    # background reindex. This is the missing wire that made activate
    # appear to do nothing for users.
    from memograph.sources.kernel_binding import swap_kernel_to_source

    await swap_kernel_to_source(request.app, tenant_id, source_id)

    return ActivateSourceResponse(
        tenant_id=tenant_id,
        previous_active_source_id=previous,
        active_source_id=source_id,
    )


@router.post(
    "/{source_id}/sync",
    response_model=SyncSourceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_source(
    source_id: str,
    request: Request,
    user: User = Depends(require_scope("admin")),
) -> SyncSourceResponse:
    """Trigger an immediate sync of one source.

    Bypasses the per-source ``sync_interval_seconds`` cadence — the
    operator's intent is "I want the data now". If the scheduler is
    not running (single-tenant install with
    ``MEMOGRAPH_SOURCES_SYNC_DISABLED=1``) we instantiate a one-shot
    sync against the registry directly so the route still works
    without leaking that the operator opted out of automatic sync.

    Returns 202 with the post-sync job state. A subsequent call
    while the first sync is still in flight returns the in-flight
    state without starting a second sync — the route is intentionally
    idempotent under concurrent calls.
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

    # Use the running scheduler if one exists so its job-state
    # bookkeeping (last_success_at, consecutive_failures, in_flight
    # guard) stays consistent with the periodic ticks. Fall back to a
    # transient scheduler when the operator disabled the loop.
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    if scheduler is None:
        from memograph.sources.sync import SyncScheduler

        scheduler = SyncScheduler(registry=registry)

    try:
        state = await scheduler.sync_now(tenant_id, source_id)
    except SourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    audit.record(
        sources_dir=registry._sources_dir(tenant_id),
        action=audit.ACTION_SYNC,
        source_id=source_id,
        source_kind=config.kind.value,
        user_id=user.id,
        tenant_id=tenant_id,
        request_id=getattr(request.state, "request_id", None),
        after={
            "in_flight": state.in_flight,
            "had_error": state.last_error is not None,
            "consecutive_failures": state.consecutive_failures,
        },
    )

    # If the synced source is the currently active one, refresh the
    # kernel's graph so newly-materialized files appear in the UI
    # without the user having to also re-activate. We only fire on
    # success — leaving a failed sync to surface its error without
    # also wiping the previous indexing state.
    if (
        state.last_error is None
        and registry.get_active(tenant_id) == source_id
    ):
        from memograph.sources.kernel_binding import reindex_active_kernel

        await reindex_active_kernel(request.app, source_id)

    return SyncSourceResponse(
        source_id=source_id,
        in_flight=state.in_flight,
        last_attempt_at=(
            state.last_attempt_at.isoformat() if state.last_attempt_at else None
        ),
        last_success_at=(
            state.last_success_at.isoformat() if state.last_success_at else None
        ),
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
    )


__all__ = ["router"]
