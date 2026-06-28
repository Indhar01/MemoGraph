"""In-process sync scheduler — Phase 2 scaffold.

The plan calls for an ARQ + Redis worker in Phase 5; that's the
production-grade story for horizontal scaling. Phase 2 ships the
single-process, single-worker version: a coroutine running on the
FastAPI event loop that ticks every N seconds, walks the registry,
and runs each warm source's ``materialize_to_vault`` on a cadence.

This is enough for:

* Solo / desktop installs — one process, sub-second tick overhead.
* Demo deployments — the hosted HF Spaces sandbox.
* Test environments — deterministic via :meth:`SyncScheduler.tick_once`.

It is **not** enough for multi-worker production. The Phase 5
swap-out drops in :class:`memograph.sources.sync.ArqScheduler`
implementing the same interface but talking to Redis. Callers only
need :class:`SyncScheduler` here; the concrete class becomes a
strategy choice at startup once both exist.

Per-source cadence comes from
``SourceConfig.params.get("sync_interval_seconds", DEFAULT_INTERVAL)``;
omit the field to use the default. Sources that opt out of automatic
sync entirely set the value to 0.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from memograph.sources.base import SourceError
from memograph.web.backend.observability import (
    record_source_documents,
    record_source_sync,
)

if TYPE_CHECKING:
    from memograph.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)


DEFAULT_INTERVAL_SECONDS = 300
"""Cadence between full syncs of one source. Picked to keep churn low
for the cloud APIs we adapt — Drive / OneDrive / Notion all rate-limit
on the order of single-digit QPS; one sync per 5 minutes is gentle. S3
listings are cheap and can be tuned down per-source via the params."""


@dataclass
class SyncJobState:
    """Mutable state for one source's sync schedule.

    Held inside the scheduler — not persisted. Restart loses
    timing state and the next tick re-runs every source; that's
    acceptable for a Phase 2 scaffold.
    """

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    in_flight: bool = False


@dataclass
class SyncScheduler:
    """In-process scheduler. Single-tenant or multi-tenant aware.

    Tick model: every ``poll_interval_seconds`` the scheduler wakes,
    iterates registry-warm sources, and triggers a sync for any
    whose ``sync_interval_seconds`` cadence has elapsed since the
    last success. New / cold sources are NOT auto-warmed by the
    scheduler — that's the registry's job on first request.
    """

    registry: SourceRegistry
    poll_interval_seconds: float = 30.0
    state: dict[tuple[str | None, str], SyncJobState] = field(default_factory=dict)
    # Fired after every successful sync. The lifespan wires this to
    # ``reindex_active_kernel`` so the kernel re-ingests when the
    # newly-materialized files belong to the active source. Optional —
    # tests don't need to wire it.
    on_synced: Callable[[str | None, str], Awaitable[None]] | None = None
    _task: asyncio.Task[None] | None = None
    _stopped: asyncio.Event | None = None

    async def start(self) -> None:
        """Begin ticking. Safe to call more than once — idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopped = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="memograph-sync-scheduler")
        logger.info("SyncScheduler started (poll=%.1fs)", self.poll_interval_seconds)

    async def stop(self) -> None:
        """Stop ticking. Waits for the in-flight tick to finish."""
        if self._stopped is None or self._task is None:
            return
        self._stopped.set()
        try:
            await asyncio.wait_for(self._task, timeout=self.poll_interval_seconds + 5)
        except asyncio.TimeoutError:
            logger.warning("SyncScheduler did not stop within grace; cancelling")
            self._task.cancel()
        self._task = None
        self._stopped = None

    async def _run(self) -> None:
        assert self._stopped is not None
        while not self._stopped.is_set():
            try:
                await self.tick_once()
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                logger.exception("scheduler tick crashed: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                continue  # normal — woke up to do the next tick

    async def tick_once(self) -> None:
        """One pass over every warm source. Public so tests can call
        it directly without waiting on the poll interval."""
        now = datetime.now(timezone.utc)
        for key, source in list(self.registry):
            tenant_id, source_id = key
            interval = self._interval_for(source)
            if interval <= 0:
                continue
            state = self.state.setdefault(key, SyncJobState())
            if state.in_flight:
                continue
            if (
                state.last_success_at is not None
                and (now - state.last_success_at).total_seconds() < interval
            ):
                continue
            await self._sync_one(source, state)

    async def sync_now(
        self,
        tenant_id: str | None,
        source_id: str,
    ) -> SyncJobState:
        """Force a sync for one source regardless of cadence.

        The route handler calls this when an operator hits
        ``POST /sources/{id}/sync``. The cadence gate in
        :meth:`tick_once` is intentionally bypassed — the operator's
        intent is "I just registered/updated this and want data
        now," and waiting 5 minutes is a worse experience than the
        small risk of double-syncing if the tick fires concurrently.

        The :attr:`SyncJobState.in_flight` flag still applies: if a
        sync is already running for this source, we skip rather than
        run a second one in parallel. The caller should retry.

        Returns the post-sync :class:`SyncJobState` so the route can
        surface success/error to the user without a second lookup.
        """
        source = self.registry.get(tenant_id, source_id)
        key = (tenant_id, source_id)
        state = self.state.setdefault(key, SyncJobState())
        if state.in_flight:
            return state
        await self._sync_one(source, state)
        return state

    async def _sync_one(self, source, state: SyncJobState) -> None:
        """Run ``materialize_to_vault`` for one source, recording metrics
        and updating job state. Errors are caught and surfaced via the
        job state; the loop never raises."""

        # We materialize to a per-source cache directory under the
        # registry's global root: <root>/<tenant?>/.sources_cache/<source_id>/
        # so different sources don't trample each other and the kernel
        # can be pointed at one cache via the active-source marker.
        tenant_dir = (
            self.registry.global_root
            if source.tenant_id is None
            else self.registry.global_root / source.tenant_id
        )
        cache = tenant_dir / ".sources_cache" / source.source_id

        state.in_flight = True
        state.last_attempt_at = datetime.now(timezone.utc)
        try:
            stats = await source.materialize_to_vault(cache)
        except SourceError as exc:
            state.last_error = str(exc)
            state.consecutive_failures += 1
            record_source_sync(
                tenant_id=source.tenant_id,
                source_kind=source.kind.value,
                result="failed",
                duration_seconds=0.0,
            )
            logger.warning(
                "sync failed for %s/%s: %s (consecutive=%d)",
                source.tenant_id,
                source.source_id,
                exc,
                state.consecutive_failures,
            )
            return
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            state.last_error = str(exc)
            state.consecutive_failures += 1
            record_source_sync(
                tenant_id=source.tenant_id,
                source_kind=source.kind.value,
                result="failed",
                duration_seconds=0.0,
            )
            logger.exception(
                "unexpected sync error for %s/%s",
                source.tenant_id,
                source.source_id,
            )
            return
        finally:
            state.in_flight = False

        state.last_success_at = datetime.now(timezone.utc)
        state.last_error = None
        state.consecutive_failures = 0
        record_source_sync(
            tenant_id=source.tenant_id,
            source_kind=source.kind.value,
            result="ok",
            duration_seconds=stats.duration_seconds,
        )
        record_source_documents(
            tenant_id=source.tenant_id,
            source_kind=source.kind.value,
            documents=stats.documents_seen,
        )
        logger.info(
            "synced %s/%s: seen=%d written=%d duration=%.2fs",
            source.tenant_id,
            source.source_id,
            stats.documents_seen,
            stats.documents_written,
            stats.duration_seconds,
        )

        # Notify the lifespan so it can refresh the kernel's graph for
        # the active tenant. We DON'T await the callback's downstream
        # work — kernel ingest is long; the scheduler tick must keep
        # moving — but we do await the callback itself so it can fire
        # off its own background task. Callback failures are logged
        # and swallowed so a buggy listener can't kill the scheduler.
        if self.on_synced is not None:
            try:
                await self.on_synced(source.tenant_id, source.source_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "on_synced callback raised for %s/%s",
                    source.tenant_id,
                    source.source_id,
                )

    def _interval_for(self, source) -> float:
        """Per-source cadence override. Returns 0 for opt-out."""
        params = source.config.params if source.config else {}
        raw = params.get("sync_interval_seconds", DEFAULT_INTERVAL_SECONDS)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL_SECONDS


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "SyncJobState",
    "SyncScheduler",
]
