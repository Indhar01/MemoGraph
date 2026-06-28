"""Multi-worker swap coordination for source adapters.

When an operator activates a different source via
``POST /api/v1/sources/{id}/activate``, the request lands on exactly
one uvicorn worker. That worker rewrites the ``_active.json`` marker
on disk, but the other workers in the pool have already cached the
previous active-source decision in their in-memory state and won't
notice the change until their next probe.

This module solves that. A :class:`SwapCoordinator` is started on
every worker at lifespan boot. The worker that handles the activate
request calls :meth:`publish_swap`; all workers (including the
publisher) receive the event through their subscription and call the
registry's :meth:`SourceRegistry.notify_remote_swap` hook, which
clears the in-memory active-source cache so the next read picks up
the new value from disk.

Two implementations:

* :class:`NullSwapCoordinator` — no-op. The default. Single-worker
  installs and the unit-test path use this; the publish call is a
  no-op and there is no subscriber loop.
* :class:`RedisSwapCoordinator` — opt-in. Set
  ``MEMOGRAPH_REDIS_URL`` (and install ``memograph[redis]``) to
  enable. Pub/sub over the configured channel; one task per worker
  listens and dispatches events back into the registry.

The contract between coordinator and registry is intentionally tiny:
the registry exposes ``notify_remote_swap(tenant_id, source_id)``
which is called once per received event. The coordinator never
touches the filesystem.

Failure modes are visible, not silent:

* Pub/sub publish failures are logged at WARNING and re-raised so
  the activate route surfaces the underlying error. Operators must
  see when Redis is down — a swap that "succeeds" on one worker but
  doesn't propagate is a footgun.
* Subscriber disconnects are logged and the subscriber task
  exponential-backs-off-and-retries (with a cap) rather than dying.
  An unreachable Redis for a few seconds shouldn't kill the worker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from memograph.sources.registry import SourceRegistry


DEFAULT_CHANNEL = "memograph:sources:swap"
"""Pub/sub channel used for source-activation events. Operators
running multiple MemoGraph deployments against the same Redis can
override via ``MEMOGRAPH_REDIS_SWAP_CHANNEL`` to keep their event
streams separate."""

# Backoff bounds for the subscriber reconnect loop. Picked so a
# transient Redis blip (a couple of seconds) recovers fast while a
# long outage doesn't spam the logs.
_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


class SwapCoordinator(Protocol):
    """Coordinator contract.

    The registry expects exactly these three methods. Adding more
    is fine; removing any of them breaks the lifespan wiring.
    """

    async def start(self, registry: "SourceRegistry") -> None: ...
    async def stop(self) -> None: ...
    async def publish_swap(self, tenant_id: str | None, source_id: str) -> None: ...


@dataclass
class NullSwapCoordinator:
    """Single-process default. No external dependencies, no I/O.

    The activate route still calls :meth:`publish_swap` — keeping
    the call shape uniform means a single env-var flip enables
    multi-worker coordination without code changes anywhere else.
    """

    async def start(self, registry: "SourceRegistry") -> None:
        # Stash a weak ref so a subclass can override start() without
        # caring about the parameter. The null coordinator doesn't
        # need it.
        return None

    async def stop(self) -> None:
        return None

    async def publish_swap(self, tenant_id: str | None, source_id: str) -> None:
        logger.debug(
            "NullSwapCoordinator: swap announced locally only "
            "(tenant=%s source_id=%s)",
            tenant_id,
            source_id,
        )


@dataclass
class RedisSwapCoordinator:
    """Redis-pub/sub-backed coordinator.

    Each worker publishes on activate and subscribes for incoming
    swap events. The publisher receives its own event back too,
    which is fine — the registry's ``notify_remote_swap`` is
    idempotent (clearing an already-cleared cache is a no-op).
    """

    url: str
    channel: str = DEFAULT_CHANNEL

    _registry: "SourceRegistry | None" = None
    _client: Any = None
    _pubsub: Any = None
    _task: asyncio.Task[None] | None = None
    _stopped: asyncio.Event | None = None

    async def start(self, registry: "SourceRegistry") -> None:
        if self._task is not None and not self._task.done():
            return
        self._registry = registry
        self._stopped = asyncio.Event()

        # Lazy import so memograph[redis] stays optional. We import
        # the asyncio shim explicitly (redis.asyncio) — the sync
        # client would block the event loop.
        try:
            import redis.asyncio as redis_async
        except ImportError as exc:
            raise RuntimeError(
                "RedisSwapCoordinator requires the 'redis' package. "
                "Install with: pip install 'memograph[redis]'"
            ) from exc

        self._client = redis_async.from_url(
            self.url, encoding="utf-8", decode_responses=True
        )
        # Confirm we can reach Redis before announcing readiness; a
        # PING failure here fails-fast at boot rather than at the
        # first activate call.
        try:
            await self._client.ping()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"RedisSwapCoordinator could not reach Redis at {self.url}: {exc}"
            ) from exc

        self._task = asyncio.create_task(
            self._subscribe_loop(), name="memograph-swap-subscriber"
        )
        logger.info(
            "RedisSwapCoordinator started (channel=%s url=%s)",
            self.channel,
            _mask_url(self.url),
        )

    async def stop(self) -> None:
        if self._stopped is not None:
            self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.close()
            except Exception:  # noqa: BLE001
                pass
            self._pubsub = None
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        self._stopped = None
        logger.info("RedisSwapCoordinator stopped")

    async def publish_swap(self, tenant_id: str | None, source_id: str) -> None:
        if self._client is None:
            raise RuntimeError(
                "RedisSwapCoordinator.publish_swap called before start()"
            )
        payload = json.dumps({"tenant_id": tenant_id, "source_id": source_id})
        await self._client.publish(self.channel, payload)
        logger.debug(
            "published swap event tenant=%s source_id=%s",
            tenant_id,
            source_id,
        )

    async def _subscribe_loop(self) -> None:
        """Long-lived subscriber with backoff on disconnect."""
        assert self._stopped is not None
        delay = _RECONNECT_MIN_SECONDS
        while not self._stopped.is_set():
            try:
                self._pubsub = self._client.pubsub()
                await self._pubsub.subscribe(self.channel)
                logger.debug("subscribed to %s", self.channel)
                # On a clean connection, reset the backoff so the
                # next disconnect starts fresh.
                delay = _RECONNECT_MIN_SECONDS
                async for message in self._pubsub.listen():
                    if self._stopped.is_set():
                        break
                    if message.get("type") != "message":
                        continue
                    await self._handle_event(message.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "swap subscriber lost connection (%s); reconnecting in %.1fs",
                    exc,
                    delay,
                )
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=delay)
                    # _stopped was set — exit the outer while.
                    return
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, _RECONNECT_MAX_SECONDS)
            finally:
                if self._pubsub is not None:
                    try:
                        await self._pubsub.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._pubsub = None

    async def _handle_event(self, raw: Any) -> None:
        """Parse one published payload and dispatch to the registry."""
        if not isinstance(raw, str):
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("swap subscriber dropped malformed payload: %r", raw)
            return
        tenant_id = data.get("tenant_id")
        source_id = data.get("source_id")
        if not isinstance(source_id, str):
            return
        if tenant_id is not None and not isinstance(tenant_id, str):
            return
        assert self._registry is not None
        try:
            self._registry.notify_remote_swap(tenant_id, source_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "registry rejected remote swap event (tenant=%s source_id=%s): %s",
                tenant_id,
                source_id,
                exc,
            )


def coordinator_from_env() -> SwapCoordinator:
    """Pick a coordinator implementation based on env config.

    Returns :class:`NullSwapCoordinator` unless ``MEMOGRAPH_REDIS_URL``
    is set. The caller still has to call :meth:`SwapCoordinator.start`;
    this function does no I/O.
    """
    url = os.environ.get("MEMOGRAPH_REDIS_URL", "").strip()
    if not url:
        return NullSwapCoordinator()
    channel = (
        os.environ.get("MEMOGRAPH_REDIS_SWAP_CHANNEL", "").strip() or DEFAULT_CHANNEL
    )
    return RedisSwapCoordinator(url=url, channel=channel)


def _mask_url(url: str) -> str:
    """Redact credentials from a Redis URL for log output."""
    # redis://[:password@]host:port/db — strip the userinfo segment if
    # present so passwords don't end up in logs.
    if "@" in url:
        prefix, rest = url.split("@", 1)
        scheme = prefix.split("://", 1)[0] if "://" in prefix else ""
        return f"{scheme}://***@{rest}" if scheme else f"***@{rest}"
    return url


__all__ = [
    "DEFAULT_CHANNEL",
    "NullSwapCoordinator",
    "RedisSwapCoordinator",
    "SwapCoordinator",
    "coordinator_from_env",
]
