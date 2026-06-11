# ADR 0001: Tenancy Model — Kernel-Per-Tenant with LRU Eviction

- **Status:** Accepted (2026-06-11) for v1.0; revisit at v2.0.
- **Phase:** 3.0
- **Decided by:** Project owner.
- **Implementers of v1:** Phase 3.1–3.7 work.

## Context

Up to and including 0.3.x, `MemoryKernel` is a single-tenant object: one
vault directory, one in-memory `VaultGraph`, one set of caches, one
swarm orchestrator. To ship MemoGraph as multi-tenant SaaS we need
isolation guarantees stronger than "trust the caller passes the right
`vault_path`."

Two architectures are on the table.

### Option A — kernel-per-tenant with LRU eviction

A `TenantRegistry` holds a bounded LRU map of `tenant_id → MemoryKernel`.
Cold tenants are evicted from RAM; warm tenants serve requests
in-process. Each tenant gets its own directory under
`<global_root>/<tenant_id>/`, its own caches, its own swarm
pheromone state.

**Pros**
- Minimal change to kernel internals — every existing invariant about
  `self.graph`, `self._graph_lock`, `self.indexer` continues to hold
  *per kernel instance*.
- Isolation is filesystem-level. The strongest possible boundary for a
  Python in-process system: a path-traversal vulnerability in any one
  route can at worst write within one tenant directory (Phase 0
  `_safe_path` already enforces this at the storage layer).
- Easy mental model. "Each tenant looks like a single-tenant
  MemoGraph" maps cleanly to today's tests, today's docs, and today's
  on-prem distribution story.
- Cold-start cost is bounded. With Phase 1.3 cache schema versioning,
  loading a cold tenant is a single `ingest()` over its vault dir.

**Cons**
- RAM grows linearly with warm tenants. With ~50 MB warm per tenant
  (graph + embedding cache + swarm pheromone), a 16 GB pod tops out
  near 300 warm tenants. Beyond that we need horizontal sharding
  with sticky routing (consistent hashing on tenant_id) or pay the
  cold-start penalty more often.
- Embedding cache is duplicated per tenant even when content overlaps.
  Acceptable: cross-tenant cache sharing is forbidden by design (see
  *Isolation invariants* below).

### Option B — single shared kernel, `tenant_id` threaded through everything

`tenant_id` becomes a parameter on every public kernel call.
`VaultGraph` becomes `MultiTenantGraph` keyed by `(tenant_id, node_id)`.
Locks shrink to per-tenant.

**Pros**
- Lower per-tenant fixed cost. Scales to millions of small tenants
  without warm-cache eviction.
- One process holds one set of caches. Easier to instrument
  centrally.

**Cons**
- Every `kernel.*` signature changes; every test changes; every MCP
  tool changes.
- Isolation is logical, not filesystem. One missed `WHERE tenant_id =
  ?` (or its in-memory equivalent) is a confidentiality breach. SOC 2
  auditors and customer security reviews will not accept this without
  significant supporting evidence.
- The swarm, GAM scorer, action logger, and all `_enhanced` variants
  also need to gain a `tenant_id` parameter. Realistically ~3× the
  code-touch of Option A.

## Decision

**v1.0 ships Option A.** v2.0 may migrate to Option B if RAM ceiling
becomes a real constraint. Option A first because:

1. **Filesystem isolation is the strongest defensible boundary** for
   the kind of customer who will buy the first commercial license.
   A pen-test report that cites "cross-tenant data leak via missing
   `WHERE tenant_id` filter" is a category of finding we cannot
   produce in Option A.
2. **It does not require touching `kernel.py`** beyond a constructor
   argument and the addition of an optional `tenant_id` field on
   audit-log records (already added in Phase 1.1c). All other Phase 3
   work is in *new* files.
3. **The migration path to Option B is real, not hypothetical.** Once
   we have telemetry on per-tenant RAM (Phase 2.1 already exposes
   this), a pod-level cap of 300 warm tenants is operationally
   manageable for a long time.

## Isolation invariants (binding)

These invariants are how the implementation will be tested. Any
violation = release blocker.

1. **Filesystem.** `TenantStorage(tenant_id="foo")` cannot read or
   write outside `<global_root>/foo/`. The Phase 0 `_safe_path` check
   is reused, with `<global_root>/<tenant_id>` as the new root.
2. **Kernel objects.** `TenantRegistry.for_tenant(tid)` returns a
   `MemoryKernel` whose `vault_path` is exactly the tenant directory.
   The same call with a different `tid` returns a different kernel
   instance (or an LRU-evicted slot reload of the same instance — but
   never one tenant's kernel handed out under another tenant's id).
3. **Embedding cache.** Cache files live inside the tenant directory.
   Hash collisions across tenants do not cause cache reuse: the cache
   key is `(content_hash,)` *within* a tenant — there is no global
   cache across tenants.
4. **Audit log.** Every `Action` carries a `tenant_id` (already in the
   schema as of Phase 1.1c). The per-tenant log file is the
   authoritative compliance-export source.
5. **Swarm.** Pheromone trails per tenant. A tenant's offboarding
   cancels in-flight cycles for that tenant before purging files.
6. **HTTP routes.** Every route under `/api/v1/` (except liveness,
   readiness, metrics, and `/api/v1/auth/me`) resolves the tenant
   from auth context, then passes through `registry.for_tenant(...)`.
   No route accepts a `tenant_id` query parameter from the client —
   the tenant comes from the trusted token, not the URL.
7. **Admin routes.** `/api/v1/admin/tenants/*` are gated by an
   `admin` scope. They are the *only* routes that can name a
   `tenant_id` other than the caller's own.

## Capacity model

| Resource | Per warm tenant | Notes |
|---|---|---|
| Graph + indexer | ~10 MB | Scales with vault size; baseline for 1k-memory vault. |
| Embedding cache (in-RAM tier) | ~30 MB | LRU bounded; spillover lives on disk. |
| Swarm pheromone | ~1 MB | Per ACO trail; cap configurable. |
| Misc (locks, action-log buffer) | ~2 MB | |
| **Total per warm tenant** | **~45 MB** | Round to 50 MB for headroom. |

A 16 GB pod with 4 GB reserved for the OS, web framework, and
admin-route handlers can carry **~240 warm tenants**. Above that, we
shard horizontally with sticky tenant→pod routing.

## Migration

Existing single-tenant deployments become a single-tenant tenancy
deployment with `tenant_id="default"`:

```
<old vault path>/  -->  <new global root>/default/
```

A migration tool (Phase 3.7 deliverable) performs the rename and
updates `MEMOGRAPH_VAULT` to `MEMOGRAPH_GLOBAL_ROOT` in the deployer's
env file.

## Out of scope for v1

- **Cross-tenant search.** Not supported; not exposed.
- **Tenant-of-tenants nesting.** Flat namespace only.
- **Memory-level ACL within a tenant.** Deferred to v1.1; v1 ships
  tenant-scoped roles only (owner / editor / viewer).
- **Encryption at rest with per-tenant KMS keys.** Phase 5 work; v1
  relies on filesystem-level encryption provided by the host.

## Test obligations

Phase 3 lands a `tests/tenancy/` suite. The release-blocking test:
spin up two tenants concurrently, write content into each, then for
every public route and every kernel method assert that

- calling without tenant context → deny,
- calling with the *wrong* tenant context → either deny or empty
  results, never the other tenant's data,
- the per-tenant action log contains only the calling tenant's
  events,
- a deletion of one tenant leaves the other tenant byte-identical.

## References

- Concurrency invariants: [docs/CONCURRENCY.md](../CONCURRENCY.md)
- Path traversal defense: [memograph/storage/vault.py](../../memograph/storage/vault.py)
- Audit-log tenant_id field: [memograph/core/action_logger.py](../../memograph/core/action_logger.py)
- Auth identity propagation: [memograph/web/backend/auth.py](../../memograph/web/backend/auth.py)
