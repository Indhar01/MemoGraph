# ADR 0002: Storage Adapter Strategy

- **Status:** In implementation (2026-06-26). Phases 1–5 landed behind
  `MEMOGRAPH_SOURCES_ENABLED=1`: Phase 1 (LocalSource + registry +
  audit + Prometheus + admin-scoped routes), Phase 2 (S3 + Notion +
  in-process SyncScheduler), Phase 3 (Google Drive OAuth with PKCE +
  encrypted token store + Drive v3 REST), Phase 4 (OneDrive /
  SharePoint via Microsoft Graph), Phase 5 (frontend SourcesPage with
  AddSourceWizard, health pills, activate/delete, OAuth redirect
  handling). Outstanding before the flag flips on by default: Redis
  pub/sub coordinated multi-worker swap, Playwright e2e coverage of
  the wizard, Google OAuth app verification for the hosted multi-
  tenant story. Accepted 2026-06-12; local filesystem remains
  canonical through v1.0 with pluggable adapters arriving in v1.1+.
- **Phase:** post-3.7 (storage extensibility roadmap).
- **Decided by:** Project owner.
- **Supersedes:** Nothing. Complements [ADR 0001](0001-tenancy-model.md).
- **Implementation:** [memograph/sources/](../../memograph/sources/),
  [memograph/web/backend/routes/sources.py](../../memograph/web/backend/routes/sources.py),
  [tests/sources/](../../tests/sources/),
  [tests/web/test_sources_routes.py](../../tests/web/test_sources_routes.py).

## Context

MemoGraph today stores every memory as a `.md` file in a vault
directory. The on-disk shape is the source of truth; cache files
(`.memograph_cache.json`, `.memograph_graph.json`,
`.memograph_embeddings.json`) are derived data that regenerate
from the markdown.

The single-vault-on-local-disk model has carried the project from
0.1 through 0.3 cleanly. Multi-tenancy (Phase 3) added a tenant
prefix to the path layout (`<global_root>/<tenant_id>/`) but did
not change the storage primitive — a `VaultStorage` instance still
wraps a directory, full stop.

The question this ADR addresses: **as we move toward 1.0, should
the storage primitive stay file-system-only, or do we make it
pluggable so users can put their vault in a Google Drive folder, a
private GitHub repo, an S3 bucket, etc.?**

This is *not* a "rip out the local filesystem" decision. The
filesystem path is fast, simple, well-tested, and the right answer
for >90% of deployments. The decision is whether to extend the
abstraction now in service of three concrete user asks that have
come up since multi-tenancy shipped.

## The user asks driving this

1. **"Can I host MemoGraph for free, with my data in my Google
   Workspace?"** — the user wants their Drive to be the durable
   store, with MemoGraph as the query/AI layer on top. Asked in
   the post-Phase-3.7 hosting conversation; documented in
   [HOSTING_GUIDE.md](../HOSTING_GUIDE.md) and
   [GOOGLE_WORKSPACE_SETUP.md](../GOOGLE_WORKSPACE_SETUP.md).
2. **"My notes are markdown and I want git history on every
   change."** — the user wants the vault to be a git working tree;
   commits-on-write give them blame, diff, branching, PR review,
   and free CDN-backed sync via GitHub.
3. **"I run MemoGraph in Cloud Run and I want vault state in object
   storage."** — the user wants S3 / GCS / R2 as the backing store
   so the compute layer can be stateless.

All three reduce to the same architectural question: can the
vault be something other than a local directory?

## Decision

**Yes, but staged.** We commit to extending the storage layer so
non-filesystem backends are possible, and we order the work so
the highest-value backend ships first.

### Order of work

| Phase | Adapter | Effort | When |
|---|---|---|---|
| 0 | `LocalFilesystemBackend` (refactor of today's `VaultStorage`) | Days | First — extracts the interface |
| 1 | `GitVaultStorage` — git working tree | 1–2 weeks | Highest user-value, lowest risk |
| 2 | `DriveBackupBackend` — Drive as portability backup, not primary | Days | Cron + service account; doc-ware today, code soon |
| 3 | `S3CompatibleBackend` — object storage primary | 2–3 weeks | Stateless-compute users |
| 4 | `DriveVaultBackend` — Drive as primary store | 4–8 weeks | Only if (3) didn't satisfy the use case |

Phases 0–2 are committed for v1.1. Phases 3 and 4 are gated on
demand — we'll do them when a real user asks, not before.

### Why this order

- **Phase 0 (interface extraction)** is necessary before any
  adapter; we won't fork the storage code to add backends.
- **Phase 1 (Git)** is the smallest implementation that delivers
  the most user value. Git semantics map onto MemoGraph's existing
  invariants almost exactly (a working tree *is* a directory plus
  a `.git/` we ignore in glob), and conflict resolution is git's
  job, not ours. Performance characteristics are close enough to
  local fs to skip benchmarks.
- **Phase 2 (Drive backup)** unblocks the Workspace-trust story
  without taking on Drive's API quotas, latency, or sync semantics
  in the hot path. Highest user-trust value per engineer-hour.
- **Phase 3 (S3-compatible)** is the right pattern for stateless
  compute (Cloud Run, Lambda, Fly.io machines that scale to zero).
  Implementations should target the S3 API; users can point at
  AWS, Backblaze B2, Cloudflare R2, GCS via interop, MinIO, etc.
- **Phase 4 (Drive primary)** is intentionally last. The storage
  cost doesn't actually go to zero (a local cache mirror is
  required to make queries fast enough), and the engineering cost
  is high (two-way sync, conflict resolution, change-detection
  webhooks, OAuth refresh-token flow, quota-aware throttling).
  Worth doing only if a customer specifically requires it; the
  Phase 2 backup flow gives us 90% of the trust story at 5% of
  the cost.

## The interface

The minimum surface a backend must support:

```python
class StorageBackend(Protocol):
    """Read/write/list primitives for a vault.

    Implementations may add caching, batching, or async optimisations
    behind this interface. The kernel sees only what's defined here.
    """

    def read_text(self, relpath: str) -> str: ...
    def write_text(self, relpath: str, content: str) -> None: ...
    def delete(self, relpath: str) -> bool: ...
    def list_markdown(self) -> list[str]: ...
    def stat_mtime(self, relpath: str) -> float: ...
    def vault_size_bytes(self) -> int: ...
    # Path-traversal containment is enforced inside write_text;
    # callers cannot escape the vault root via crafted relpaths.
```

The existing `VaultStorage` already implements (or trivially can
implement) every method here. Phase 0 is the refactor that makes
the existing class an implementation of the protocol; existing
call sites change only in their type annotation.

### Caching

Every adapter except `LocalFilesystemBackend` will compose with a
local-disk read-through cache (`.memograph_cache/<adapter>/`)
keyed by `(relpath, etag-or-mtime)`. The kernel doesn't know about
the cache; it talks to the adapter. This keeps the hot path fast
even when the backend is a 200ms-RTT remote API.

### Auth

Adapter-specific auth (OAuth refresh tokens for Drive, deploy keys
for git, IAM credentials for S3) is handled inside the adapter,
not threaded through the kernel. The kernel passes a `tenant_id`
context; the adapter resolves credentials from that.

## Consequences

**Good**

- The Workspace-trust story becomes shippable without taking on
  Drive's hard problems immediately.
- GitHub-vault deployment becomes a real option, which is
  particularly compelling for the developer audience that already
  lives in git.
- Stateless-compute hosting (Cloud Run, etc.) becomes viable.
- The codebase has a clean extension point so future backends
  (Notion, S3 Glacier for archival, IPFS for the truly
  decentralized crowd) cost weeks instead of being architectural
  rewrites.

**Tradeoffs**

- Every adapter is a new test surface. We commit to the same
  isolation-test gate that Phase 3 enforces — the
  [tests/tenancy/test_isolation_e2e.py](../../tests/tenancy/test_isolation_e2e.py)
  shape will be reused per adapter, parameterised over the
  backend.
- The protocol risks growing as adapters need new operations. We
  resist this by routing edge cases through the adapter's
  configuration rather than expanding the interface.
- Local-fs users see a small interface-cost: an extra
  abstraction layer between the kernel and disk. This is a
  one-time refactor cost; the runtime cost is zero (the local
  adapter is a thin pass-through).

## Out of scope

- Encrypted-at-rest storage. KMS-managed encryption is its own
  orthogonal axis; an `EncryptedBackend` wrapper around any of the
  above will compose cleanly. Tracked under Phase 5 (compliance).
- Replication / multi-region. Single-source-of-truth per backend.
  HA is the operator's problem; we make backups easy and call
  that done for v1.x.
- Distributed graph state across nodes. The graph is per-tenant
  in-RAM; horizontal scale of a single tenant is not in scope
  for this ADR.

## Status checks

| Question | Answer (2026-06-12) |
|---|---|
| Has Phase 0 (interface extraction) started? | No |
| Is `GitVaultStorage` blocking any current customer? | No |
| Is Drive backup blocking any current customer? | No, but it's the most-asked feature in the hosting conversation |
| When do we start Phase 0? | When the first concrete adapter is needed (currently: when GitHub-vault gets a customer ask, or v1.0 cleanup begins, whichever first) |
