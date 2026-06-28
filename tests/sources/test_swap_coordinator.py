"""Tests for the multi-worker swap coordinator.

These cover three layers:

* :class:`NullSwapCoordinator` — sanity-check the no-op default so
  single-worker installs don't pay a hidden cost.
* :func:`coordinator_from_env` — env-var dispatch.
* :class:`RedisSwapCoordinator` — exercised against a hand-rolled
  in-memory fake (modeled on ``redis.asyncio.client.PubSub``), which
  lets us assert publish + receive + reconnect semantics without
  needing a real Redis. ``fakeredis`` would also work but adds a
  dep; the surface we need is small enough that a bespoke fake is
  cheaper.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from memograph.sources.base import SourceConfig, SourceKind
from memograph.sources.registry import SourceRegistry
from memograph.sources.swap_coordinator import (
    DEFAULT_CHANNEL,
    NullSwapCoordinator,
    RedisSwapCoordinator,
    coordinator_from_env,
)


def _local_config(path: Path, source_id: str = "primary") -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        kind=SourceKind.LOCAL,
        display_name="Primary",
        params={"path": str(path)},
    )


# --- coordinator_from_env ---


class TestCoordinatorFromEnv:
    def test_returns_null_when_redis_url_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("MEMOGRAPH_REDIS_URL", raising=False)
        c = coordinator_from_env()
        assert isinstance(c, NullSwapCoordinator)

    def test_returns_redis_when_url_set(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_REDIS_URL", "redis://localhost:6379/0")
        c = coordinator_from_env()
        assert isinstance(c, RedisSwapCoordinator)
        assert c.url == "redis://localhost:6379/0"
        assert c.channel == DEFAULT_CHANNEL

    def test_honours_custom_channel(self, monkeypatch) -> None:
        monkeypatch.setenv("MEMOGRAPH_REDIS_URL", "redis://r:1")
        monkeypatch.setenv("MEMOGRAPH_REDIS_SWAP_CHANNEL", "custom:chan")
        c = coordinator_from_env()
        assert isinstance(c, RedisSwapCoordinator)
        assert c.channel == "custom:chan"


# --- NullSwapCoordinator ---


class TestNullCoordinator:
    @pytest.mark.asyncio
    async def test_publish_is_silent_noop(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        c = NullSwapCoordinator()
        await c.start(registry)
        # No raise, no I/O — the coordinator is a sink.
        await c.publish_swap(None, "primary")
        await c.stop()


# --- RedisSwapCoordinator (against fake) ---


class _FakePubSub:
    """Minimal stand-in for ``redis.asyncio.client.PubSub``.

    Implements ``subscribe`` + ``listen`` + ``close``. Messages are
    pulled from a shared queue on the parent fake client. Each
    listener yields a single subscription-confirmation message
    first (matching real Redis behavior) so the coordinator can't
    accidentally treat the ack as a data event.
    """

    def __init__(self, queue: asyncio.Queue[Any], channel: str) -> None:
        self._queue = queue
        self._channel = channel
        self._closed = False

    async def subscribe(self, channel: str) -> None:
        # Match the real client's spelling.
        assert channel == self._channel
        await self._queue.put({"type": "subscribe", "channel": channel})

    async def listen(self):
        while not self._closed:
            msg = await self._queue.get()
            yield msg
            if self._closed:
                return

    async def close(self) -> None:
        self._closed = True
        # Drop a sentinel so a pending ``await self._queue.get()``
        # unblocks even after close.
        await self._queue.put({"type": "shutdown"})


class _FakeRedisClient:
    """Minimal stand-in for ``redis.asyncio.Redis``."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.pinged = False
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def ping(self) -> bool:
        self.pinged = True
        return True

    def pubsub(self):
        return _FakePubSub(self.queue, DEFAULT_CHANNEL)

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        await self.queue.put({"type": "message", "channel": channel, "data": payload})
        return 1

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def patched_redis(monkeypatch):
    """Replace ``redis.asyncio.from_url`` with a factory that hands
    back a fresh fake client. Returns the fake for assertions."""
    import sys
    import types

    fakes: list[_FakeRedisClient] = []

    def _from_url(url: str, **_kw):  # noqa: ARG001
        client = _FakeRedisClient()
        fakes.append(client)
        return client

    fake_module = types.SimpleNamespace(from_url=_from_url)
    # Build a parent ``redis`` module if the real one isn't installed,
    # then patch its ``asyncio`` submodule attribute. Either way, the
    # coordinator's ``import redis.asyncio as redis_async`` resolves
    # to our fake.
    redis_parent = sys.modules.get("redis")
    if redis_parent is None:
        redis_parent = types.ModuleType("redis")
        monkeypatch.setitem(sys.modules, "redis", redis_parent)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_module)
    setattr(redis_parent, "asyncio", fake_module)
    return fakes


class TestRedisCoordinator:
    @pytest.mark.asyncio
    async def test_start_pings_redis(self, tmp_path: Path, patched_redis) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        c = RedisSwapCoordinator(url="redis://fake")
        await c.start(registry)
        assert len(patched_redis) == 1
        assert patched_redis[0].pinged is True
        await c.stop()
        assert patched_redis[0].closed is True

    @pytest.mark.asyncio
    async def test_publish_publishes_payload(
        self, tmp_path: Path, patched_redis
    ) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        c = RedisSwapCoordinator(url="redis://fake")
        await c.start(registry)
        await c.publish_swap("tenant-a", "primary")
        # Drain a moment so the subscriber loop processes the message.
        await asyncio.sleep(0.05)
        fake = patched_redis[0]
        assert fake.published
        chan, payload = fake.published[-1]
        assert chan == DEFAULT_CHANNEL
        assert '"tenant_id": "tenant-a"' in payload
        assert '"source_id": "primary"' in payload
        await c.stop()

    @pytest.mark.asyncio
    async def test_received_event_clears_cache(
        self, tmp_path: Path, patched_redis
    ) -> None:
        # Seed the registry with one source + activate it so the
        # cache has a known value; then publish a swap to a
        # different id and observe the cache reset.
        vault = tmp_path / "v"; vault.mkdir()
        other = tmp_path / "v2"; other.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_local_config(vault, source_id="primary"))
        registry.register(_local_config(other, source_id="secondary"))
        registry.set_active(None, "primary")
        # Warm the cache by reading.
        assert registry.get_active(None) == "primary"
        assert registry._active_cache[None] == "primary"

        c = RedisSwapCoordinator(url="redis://fake")
        await c.start(registry)
        await c.publish_swap(None, "secondary")
        # Subscriber processes asynchronously; give it a tick.
        await asyncio.sleep(0.1)
        # Cache was invalidated.
        assert None not in registry._active_cache
        # Next read picks up the disk value. We didn't actually
        # update _active.json from the peer's side, so it still
        # reads "primary" — but the *point* is that the cache no
        # longer pins the stale value. In a real deployment, the
        # peer worker wrote the marker before publishing.
        assert registry.get_active(None) == "primary"
        await c.stop()

    @pytest.mark.asyncio
    async def test_malformed_payload_is_dropped(
        self, tmp_path: Path, patched_redis
    ) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        c = RedisSwapCoordinator(url="redis://fake")
        await c.start(registry)
        fake = patched_redis[0]
        # Inject a non-JSON payload directly into the queue.
        await fake.queue.put(
            {"type": "message", "channel": DEFAULT_CHANNEL, "data": "not-json"}
        )
        await asyncio.sleep(0.05)
        # Then a missing-source-id payload.
        await fake.queue.put(
            {"type": "message", "channel": DEFAULT_CHANNEL, "data": '{"tenant_id": "x"}'}
        )
        await asyncio.sleep(0.05)
        # Coordinator survived; we can stop cleanly.
        await c.stop()


class TestRegistryRemoteSwapHook:
    def test_notify_clears_cache(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"; vault.mkdir()
        registry = SourceRegistry(global_root=tmp_path / "global")
        registry.register(_local_config(vault))
        registry.set_active(None, "primary")
        # Warm the cache.
        assert registry.get_active(None) == "primary"
        assert None in registry._active_cache
        registry.notify_remote_swap(None, "anything")
        assert None not in registry._active_cache

    def test_notify_is_idempotent_on_cold_cache(self, tmp_path: Path) -> None:
        registry = SourceRegistry(global_root=tmp_path / "global")
        # No prior reads — cache is cold.
        registry.notify_remote_swap("tenant-z", "never-existed")  # no raise
        assert "tenant-z" not in registry._active_cache
