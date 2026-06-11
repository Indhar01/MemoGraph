# MemoGraph Architecture

This document records the canonical architecture decisions that are not
obvious from reading the code alone. Pair this with [CLAUDE.md](../CLAUDE.md)
for the layer-by-layer overview.

## Canonical kernel

**`memograph.core.kernel.MemoryKernel` is the canonical kernel class.** All
new code — internal or third-party — should import it directly:

```python
from memograph import MemoryKernel
# or, equivalently:
from memograph.core.kernel import MemoryKernel
```

`MemoryKernel` already includes the features that historically lived in
separate classes — async ingestion, batch operations, the embedding cache,
input validation, and (optionally) Graph Attention Memory scoring. The
constructor flags below select between them:

| Constructor flag           | Default | What it enables                              |
|----------------------------|---------|----------------------------------------------|
| `enable_cache`             | True    | Disk-backed cache of mtime/embeddings/graph. |
| `validate_inputs`          | True    | Pydantic-style input validation in setters.  |
| `max_concurrent`           | 10      | Asyncio semaphore for `ingest_async`.        |
| `use_gam`                  | False   | Switch to the GAM retriever path.            |
| `gam_config: GAMConfig`    | None    | Tuning for GAM scoring.                      |

### Back-compat shims

Four modules in `memograph/core/` exist purely to keep older import paths
working. Each is a thin wrapper around `MemoryKernel`; none implements any
behaviour that the canonical class does not. Treat them as deprecated for
new code — Phase 4 of the enterprise roadmap will retire them.

| Module                  | Symbol                | Replace with                                                     |
|-------------------------|-----------------------|------------------------------------------------------------------|
| `core.kernel_async`     | `AsyncMemoryKernel`   | `MemoryKernel` (alias re-export, identical class).               |
| `core.kernel_batch`     | `BatchMemoryKernel`   | `MemoryKernel` (alias re-export, identical class).               |
| `core.kernel_enhanced`  | `EnhancedMemoryKernel`| `MemoryKernel(enable_cache=True, validate_inputs=True)`.         |
| `core.kernel_gam_async` | `GAMAsyncKernel`      | `MemoryKernel(use_gam=True, gam_config=GAMConfig(...))`.         |

If you're maintaining downstream code, the migration is mechanical:
replace the symbol import and the constructor call. The deprecation
window will be at least one minor version once the 1.0 release lands.

## Storage entry point

**`memograph.storage.vault.VaultStorage` is the documented storage entry
point.** Today the kernel writes markdown directly via `Path.write_text`
(see `kernel.py:712, 1110, 2592`), bypassing `VaultStorage` entirely.
Phase 1 of the roadmap audits those direct writes; Phase 3 routes them
through `VaultStorage` so that multi-tenancy scoping has a single
choke-point. Until then, `VaultStorage.write` enforces path-traversal
defenses (added in Phase 0) so it is correct *now* even though it is
not yet on the hot path.

## What is *not* canonical (but you'll see in the tree)

- `storage/cache_enhanced.py` next to `storage/cache.py` — the `_enhanced`
  variant adds locking and version-tagging. Phase 4 collapses these into
  one module.
- `mcp/run_server_enhanced.py` next to `mcp/run_server.py` — same story:
  the `_enhanced` variant adds analytics tools. Phase 4 collapses them.

These will be retired in Phase 4. Do not start new code paths that depend
on `_enhanced` parallels.

## Public API surface

The public API is what `memograph/__init__.py` re-exports. Anything else
is internal and may move without a deprecation window. The current
exports are:

```python
MemoryKernel
MemoryType
EntityType
SmartAutoOrganizer
GAMConfig, GAMScorer, GAMRetriever
AccessTracker
MemographConfig
```

The 1.0 release (Phase 4 of the roadmap) will commit to a deprecation
policy on this surface; until then, treat it as stable-ish but pre-1.0.
