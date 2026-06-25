"""Tenant registry — LRU of warm :class:`MemoryKernel` instances (Phase 3.2).

Per ADR 0001, the v1 tenancy model is *kernel-per-tenant*. This module
keeps a bounded LRU map of warm kernels keyed by ``tenant_id``. Cold
tenants are materialized on demand from the per-tenant vault directory
managed by :class:`TenantStorage`.

This module is built as a **new file** that does not modify
``kernel.py``. The kernel still constructs itself from a single
``vault_path``. The registry is the only thing that knows about
multi-tenancy in v1; the kernel stays tenant-unaware.

Concurrency
-----------

* Lookups and evictions hold a single registry-level ``RLock``.
  Per-tenant kernel construction can be slow (file scan, embedding
  warmup), so we release the registry lock as soon as the kernel slot
  is reserved and let construction run outside the lock. A second
  caller for the same tenant during construction blocks on a
  per-tenant ``Event`` until the first construction completes — no
  thundering herd, but also no global lock held during slow IO.
* ``MemoryKernel`` carries its own ``_graph_lock`` for graph mutation
  (see ``docs/CONCURRENCY.md``); the registry does not need to
  protect any state inside the kernel.

What this module deliberately does NOT do
------------------------------------------

* No tenant-scoped quotas. That's Phase 3.6 — we'll wire it on the
  way in or out of registry calls then.
* No tenant offboarding. Eviction here is just a memory-pressure
  release; a destroyed tenant requires
  :meth:`TenantStorage.delete_tenant`.
* No flush-on-evict of cycle reports. The swarm is per-tenant in
  Phase 3.3 — the kernel-level eviction here will need to call into
  swarm shutdown when that lands.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional, TYPE_CHECKING

from memograph.storage.tenant_storage import TenantStorage, validate_tenant_id

if TYPE_CHECKING:
    from memograph.core.kernel import MemoryKernel

logger = logging.getLogger(__name__)


KernelFactory = Callable[[str], "MemoryKernel"]
"""A callable ``(vault_path) -> MemoryKernel``. Injected so tests can
substitute a stub kernel without importing the real one (avoids
pulling in heavy embedding deps during unit tests)."""


DEFAULT_MAX_WARM = 64
"""Default LRU size. Sized for a small VPS (16 GB) with ~50 MB warm
per tenant — see capacity model in ADR 0001."""


class TenantRegistry:
    """Bounded LRU of warm :class:`MemoryKernel` instances per tenant.

    Construct with a :class:`TenantStorage` and a kernel factory.
    Calling :meth:`for_tenant` returns a kernel whose ``vault_path``
    is the tenant's directory.

    Example::

        from memograph.core.kernel import MemoryKernel
        from memograph.storage.tenant_storage import TenantStorage
        from memograph.core.tenant_registry import TenantRegistry

        storage = TenantStorage("/srv/memograph/tenants")

        def factory(vault_path: str) -> MemoryKernel:
            return MemoryKernel(vault_path=vault_path)

        registry = TenantRegistry(storage, kernel_factory=factory, max_warm=64)
        kernel = registry.for_tenant("acme")
    """

    def __init__(
        self,
        storage: TenantStorage,
        kernel_factory: KernelFactory,
        max_warm: int = DEFAULT_MAX_WARM,
    ) -> None:
        if max_warm < 1:
            raise ValueError(f"max_warm must be >= 1, got {max_warm}")
        self.storage = storage
        self._kernel_factory = kernel_factory
        self.max_warm = max_warm
        self._lock = threading.RLock()
        self._warm: OrderedDict[str, MemoryKernel] = OrderedDict()
        # Per-tenant construction events so two callers for the same
        # cold tenant don't both build a kernel.
        self._building: dict[str, threading.Event] = {}

    def for_tenant(self, tenant_id: str) -> "MemoryKernel":
        """Return the warm kernel for ``tenant_id``, materializing it
        if cold. Marks the entry as most-recently-used.

        Raises :class:`InvalidTenantIdError` if the id fails validation.
        """
        validate_tenant_id(tenant_id)

        # Fast path: warm hit.
        with self._lock:
            kernel = self._warm.get(tenant_id)
            if kernel is not None:
                self._warm.move_to_end(tenant_id)
                return kernel

            # Are we (or another thread) already building this tenant?
            event = self._building.get(tenant_id)
            if event is None:
                # We claim the build slot.
                event = threading.Event()
                self._building[tenant_id] = event
                build_owner = True
            else:
                build_owner = False

        if not build_owner:
            # Another thread is constructing; wait then re-enter.
            event.wait()
            return self.for_tenant(tenant_id)

        try:
            path = self.storage.create_tenant(tenant_id)
            logger.info(f"warming tenant kernel: {tenant_id} at {path}")
            kernel = self._kernel_factory(str(path))
        except Exception:
            # Don't leave a stuck build slot on failure.
            with self._lock:
                self._building.pop(tenant_id, None)
            event.set()
            raise

        with self._lock:
            self._warm[tenant_id] = kernel
            self._warm.move_to_end(tenant_id)
            self._evict_if_needed()
            self._building.pop(tenant_id, None)
        event.set()
        return kernel

    def evict(self, tenant_id: str) -> bool:
        """Drop a tenant from the warm cache. Returns True if a warm
        entry was removed. Does not delete files; see
        :meth:`TenantStorage.delete_tenant` for that.
        """
        with self._lock:
            kernel = self._warm.pop(tenant_id, None)
        if kernel is None:
            return False
        _safe_close(kernel)
        return True

    def warm_tenants(self) -> list[str]:
        """Return tenant ids currently warm in the LRU, MRU-last order."""
        with self._lock:
            return list(self._warm.keys())

    def _evict_if_needed(self) -> None:
        # Caller holds ``self._lock``.
        while len(self._warm) > self.max_warm:
            evicted_id, kernel = self._warm.popitem(last=False)
            logger.info(f"LRU evicting tenant kernel: {evicted_id}")
            _safe_close(kernel)

    # ---- admin / inspection ----

    def usage_bytes(self, tenant_id: str) -> int:
        """Bytes on disk for the tenant. Wraps
        :meth:`TenantStorage.usage_bytes`. Available regardless of
        warm state."""
        return self.storage.usage_bytes(tenant_id)

    def known_tenants(self) -> list[str]:
        """All tenants visible on disk. Subset of these may be warm
        at any time."""
        return self.storage.list_tenants()

    def offboard(self, tenant_id: str) -> bool:
        """Evict from warm cache *and* delete the tenant's directory.

        Returns True if anything (warm slot or disk dir) was removed.
        Idempotent. Phase 3.7 GDPR runbook will wrap this with grace
        periods and final-export tarballs.
        """
        # Order matters: drop the warm kernel first so it doesn't
        # try to flush onto a directory we're about to remove.
        warm_removed = self.evict(tenant_id)
        disk_removed = self.storage.delete_tenant(tenant_id)
        return warm_removed or disk_removed


def _safe_close(kernel: Optional[Any]) -> None:
    """Best-effort kernel shutdown.

    The current ``MemoryKernel`` does not expose a ``close()``; once
    it does (Phase 3.3 wiring with the swarm), this is the single
    place that calls it. Until then, eviction just drops the
    reference and lets GC reclaim it.
    """
    if kernel is None:
        return
    closer = getattr(kernel, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            logger.exception("error closing tenant kernel; continuing eviction")


__all__ = [
    "TenantRegistry",
    "KernelFactory",
    "DEFAULT_MAX_WARM",
]
