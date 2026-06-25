"""Phase 3.2 tests for :class:`TenantRegistry`.

Bar:

* LRU evicts the least-recently-used tenant once warm count exceeds
  ``max_warm``.
* Concurrent ``for_tenant`` calls for the same cold tenant build only
  one kernel (no thundering herd).
* Per-tenant kernel paths are isolated (validated indirectly via the
  factory's ``vault_path`` argument).
* ``offboard`` evicts warm + deletes disk + is idempotent.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from memograph.core.tenant_registry import TenantRegistry
from memograph.storage.tenant_storage import InvalidTenantIdError, TenantStorage


class StubKernel:
    """Minimal stand-in for :class:`MemoryKernel`.

    The real kernel pulls in heavy embedding/indexing deps. The
    registry only cares that the factory returns *something* and that
    the same tenant id always maps back to the same instance.
    """

    instances: list["StubKernel"] = []

    def __init__(self, vault_path: str) -> None:
        self.vault_path = vault_path
        self.closed = False
        StubKernel.instances.append(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_stub_kernels():
    StubKernel.instances.clear()
    yield
    StubKernel.instances.clear()


@pytest.fixture
def registry(tmp_path):
    storage = TenantStorage(global_root=tmp_path)
    return TenantRegistry(storage, kernel_factory=StubKernel, max_warm=3)


# ---- basic lookup ----


def test_for_tenant_creates_kernel(registry, tmp_path):
    k = registry.for_tenant("acme")
    assert isinstance(k, StubKernel)
    assert k.vault_path == str((tmp_path / "acme").resolve())


def test_for_tenant_warm_hit_returns_same_instance(registry):
    a = registry.for_tenant("acme")
    b = registry.for_tenant("acme")
    assert a is b
    assert len(StubKernel.instances) == 1


def test_for_tenant_validates_id(registry):
    with pytest.raises(InvalidTenantIdError):
        registry.for_tenant("../etc")


# ---- LRU eviction ----


def test_lru_evicts_oldest(registry):
    a = registry.for_tenant("a")
    b = registry.for_tenant("b")
    c = registry.for_tenant("c")
    # max_warm=3, all warm.
    assert registry.warm_tenants() == ["a", "b", "c"]

    registry.for_tenant("d")  # evicts "a"
    assert registry.warm_tenants() == ["b", "c", "d"]
    assert a.closed is True
    assert b.closed is False
    assert c.closed is False


def test_lru_promotes_on_access(registry):
    registry.for_tenant("a")
    registry.for_tenant("b")
    registry.for_tenant("c")
    registry.for_tenant("a")  # promote a to MRU
    registry.for_tenant("d")  # evicts b (now LRU)

    assert "b" not in registry.warm_tenants()
    assert "a" in registry.warm_tenants()


def test_warm_only_grows_to_max(registry):
    for i in range(10):
        registry.for_tenant(f"t{i}")
    assert len(registry.warm_tenants()) == registry.max_warm


# ---- offboard / evict ----


def test_evict_warm_slot(registry, tmp_path):
    registry.for_tenant("acme")
    assert registry.evict("acme") is True
    assert registry.evict("acme") is False  # idempotent
    assert "acme" not in registry.warm_tenants()


def test_offboard_removes_disk_and_warm(registry, tmp_path):
    registry.for_tenant("acme")
    assert (tmp_path / "acme").exists()

    assert registry.offboard("acme") is True
    assert not (tmp_path / "acme").exists()
    assert "acme" not in registry.warm_tenants()


def test_offboard_idempotent(registry):
    assert registry.offboard("ghost") is False


def test_known_tenants_includes_cold(registry, tmp_path):
    # warm one, create another via storage only
    registry.for_tenant("warmie")
    registry.storage.create_tenant("coldie")

    known = set(registry.known_tenants())
    assert known == {"warmie", "coldie"}


# ---- thundering herd ----


def test_concurrent_for_tenant_builds_once(tmp_path):
    """20 threads racing for the same cold tenant must yield one kernel."""
    storage = TenantStorage(global_root=tmp_path)
    build_count = 0
    build_count_lock = threading.Lock()
    block_event = threading.Event()

    def slow_factory(vault_path: str) -> StubKernel:
        nonlocal build_count
        with build_count_lock:
            build_count += 1
        # Hold all callers in the build until we release. This ensures
        # the test would fail without the per-tenant Event in the
        # registry — every racing thread would otherwise enter the
        # factory.
        block_event.wait(timeout=5.0)
        return StubKernel(vault_path)

    registry = TenantRegistry(storage, kernel_factory=slow_factory, max_warm=4)

    results: list[Any] = []
    results_lock = threading.Lock()

    def get() -> None:
        k = registry.for_tenant("hotone")
        with results_lock:
            results.append(k)

    threads = [threading.Thread(target=get) for _ in range(20)]
    for t in threads:
        t.start()
    # Let the factory return.
    block_event.set()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive(), "deadlock waiting on tenant build"

    # Exactly one factory invocation; every thread got the same instance.
    assert build_count == 1
    assert len(results) == 20
    assert all(r is results[0] for r in results)


def test_concurrent_different_tenants_build_in_parallel(tmp_path):
    """Cold builds for *different* tenants must not serialize on each other."""
    storage = TenantStorage(global_root=tmp_path)
    in_factory = threading.Semaphore(0)
    proceed = threading.Event()

    def slow_factory(vault_path: str) -> StubKernel:
        in_factory.release()
        proceed.wait(timeout=5.0)
        return StubKernel(vault_path)

    registry = TenantRegistry(storage, kernel_factory=slow_factory, max_warm=8)

    threads = [
        threading.Thread(target=registry.for_tenant, args=(f"t{i}",)) for i in range(4)
    ]
    for t in threads:
        t.start()

    # Wait for all four to enter the factory simultaneously.
    for _ in range(4):
        assert in_factory.acquire(timeout=5.0), "factory did not run in parallel"

    proceed.set()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive()


# ---- factory failure cleanup ----


def test_factory_exception_clears_build_slot(tmp_path):
    storage = TenantStorage(global_root=tmp_path)

    fail_first = {"value": True}

    def maybe_failing(vault_path: str) -> StubKernel:
        if fail_first["value"]:
            fail_first["value"] = False
            raise RuntimeError("transient")
        return StubKernel(vault_path)

    registry = TenantRegistry(storage, kernel_factory=maybe_failing, max_warm=4)

    with pytest.raises(RuntimeError):
        registry.for_tenant("acme")

    # Slot must be released so the next call can retry.
    k = registry.for_tenant("acme")
    assert isinstance(k, StubKernel)


# ---- usage ----


def test_usage_bytes_proxy(registry):
    registry.for_tenant("acme")
    # Empty tenant — usage may be 0 (vault dir is empty).
    assert registry.usage_bytes("acme") == 0
