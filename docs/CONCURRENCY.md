# Concurrency model

Maps every shared mutable resource in MemoGraph to its synchronization
primitive. Maintained as part of Phase 2 of the enterprise-readiness
roadmap; updated whenever a new lock or shared structure lands.

The current target is **a single Python process** (one `MemoryKernel`
instance, one FastAPI worker). Phase 3 multi-tenancy keeps the
single-process model per tenant via `TenantRegistry`; Phase 4
horizontal scale-out across multiple processes will require a
process-external coordination layer (Redis, Postgres advisory locks)
that does not exist today.

## Inventory

| Resource | Lock | Owner | Held during |
|---|---|---|---|
| `MemoryKernel.graph` (the `VaultGraph` instance) | `threading.RLock` (`_graph_lock`) | `kernel.py:382` | All graph mutations: ingest, remember, delete, link. RLock so nested calls inside the same thread don't deadlock. |
| `MemoryKernel` async operations | `asyncio.Semaphore` (`_semaphore`, default 10) | `kernel.py:345` | Bounds parallelism on `ingest_async`, `search_async`, embedding work. Caps memory pressure under fan-out. |
| `LRUCache` (per cache instance) | `threading.Lock` (`_lock`) | `storage/cache_enhanced.py:61` | Entry insertion, eviction, hit-count update. Held for the duration of get/put — cheap ops, contention rare. |
| `DiskCache` | `threading.Lock` (`_lock`) | `storage/cache_enhanced.py:158` | Disk read/write of a single cache entry. |
| `QueryResultCache` | `threading.Lock` (`_lock`) | `storage/cache_enhanced.py:420` | TTL eviction sweeps + entry replacement. |
| `ActionLogger.history_path` | `threading.Lock` (`_lock`) | `core/action_logger.py:95` | Read-modify-write of the JSON history file. Per-instance; one logger per vault. |
| Module-level action-logger registry | `threading.Lock` (`_logger_lock`) | `core/action_logger.py:360` | Lazy creation of the singleton logger per vault path. |
| `MetricsCollector` rolling deques | `threading.Lock` (`_lock`) | `core/metrics.py:122` | Rolling-window observation insertion. |
| Module-level metrics registry | `threading.Lock` (`_metrics_lock`) | `core/metrics.py:235` | Singleton initialisation. |
| Obsidian sync queue | `asyncio.Lock` (`_queue_lock`) | `integrations/obsidian/sync.py:75` | Add/drain of the pending-changes queue. Each watcher event acquires once. |
| Swarm cycle scheduling | `asyncio.Semaphore` | `swarm/orchestrator.py:258` | Caps the number of concurrently-running agent batches per cycle. |
| Prometheus default registry | (provided by `prometheus_client`) | `web/backend/observability.py` | Counter/histogram registration; the library handles its own thread safety. |
| FastAPI request-scope state | none needed | per-request | Each request gets a fresh `request.state`; no inter-request shared mutation. |
| Auth `current_user` ContextVar | (asyncio + threading native) | `web/backend/auth.py` | Per-request identity; `ContextVar` is task-local. |

## Invariants

- **The graph cannot be read while it is being rebuilt.** All graph
  mutations acquire `_graph_lock`; reads do too. We use `RLock` so a
  search inside a remember (recursion via callbacks) doesn't deadlock.
- **Embedding cache writes never race.** Each `LRUCache` instance
  owns its lock; the disk-backed layer has its own. Hits don't touch
  the disk-cache lock.
- **Audit log writes are serialised per-vault.** The append-replace-write
  pattern in `ActionLogger.log_action` runs under the lock; concurrent
  writes from different threads see a consistent file.
- **Async fan-out is bounded.** Both `kernel._semaphore` and the swarm
  orchestrator's semaphore cap parallelism. Without these, a busy
  vault could OOM on embedding work.

## Known weak points (deferred)

- **No cross-process coordination.** Two MemoGraph workers pointed at
  the same vault directory will trample each other's caches. Phase 4
  will introduce a vault-level lockfile (sqlite `.lock`) so a running
  instance can refuse a second one and emit a clear error rather than
  corrupt state.
- **`VaultStorage.write` is not yet on the kernel hot path.** When
  Phase 3 routes writes through it, the path-traversal check should
  also acquire `_graph_lock` (or a dedicated I/O lock) so a write +
  graph rebuild can't observe a half-written file.
- **`SwarmOrchestrator` cycle reports are not flushed atomically.** A
  crash mid-cycle leaves a partial JSON. This is acceptable for now
  (cycles are idempotent) but Phase 3 multi-tenancy will need
  per-tenant atomic writes.

## How to verify

`tests/stress/test_concurrent_kernel.py` exercises concurrent
remember/search/delete against the same kernel instance. The bar is:
no exceptions, no deadlocks, and final state matches the operation
log (every successful remember is retrievable; every successful
delete is gone).

Run only the stress suite with::

    pytest tests/stress/ -m stress --no-cov

Stress tests are deselected by default (the project's
`addopts = ["-m \"not stress\""]` would normally apply, but it isn't
set; see `pyproject.toml`). Phase 4 productisation work will make
stress a default-skip marker.
