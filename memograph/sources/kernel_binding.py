"""Glue between the sources subsystem and the kernel.

The sources subsystem materializes data to a per-source cache, and
each source has a notion of where the kernel should read from when
that source is active. This module owns that mapping and the kernel
hot-swap that fires on activate.

Three public helpers:

* :func:`vault_path_for_source` — dispatch on :class:`SourceKind` to
  resolve the directory the kernel should be pointed at.
* :func:`swap_kernel_to_source` — re-construct ``app.state.kernel``
  against the source's vault path and kick off a background ingest.
* :func:`reindex_active_kernel` — used by the sync path to refresh
  the graph after a successful materialize without changing the
  vault path.

Single-tenant focus for now (``app.state.kernel``). Multi-tenant
hot-swap goes through the per-tenant kernel cache inside the
registry, which can call into the same primitives.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from memograph.core.kernel import MemoryKernel
from memograph.sources.base import SourceConfig, SourceError, SourceKind

if TYPE_CHECKING:
    from fastapi import FastAPI

    from memograph.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)


def vault_path_for_source(
    config: SourceConfig,
    registry: "SourceRegistry",
    tenant_id: str | None,
) -> Path:
    """The on-disk directory the kernel should read when this source is active.

    - :attr:`SourceKind.LOCAL`: the source's own ``params['path']``.
      No copy, no cache — the source IS the vault.
    - Everything else (S3, GDrive, OneDrive, Notion via Nango): the
      per-source cache directory under the registry's global root,
      kept in lockstep with :func:`memograph.sources.sync._sync_one`.
    """
    if config.kind is SourceKind.LOCAL:
        path = config.params.get("path")
        if not path:
            raise SourceError(
                f"LocalSource {config.source_id!r} has no params['path']; "
                "cannot resolve a kernel vault path"
            )
        return Path(path).expanduser().resolve()
    tenant_dir = (
        registry.global_root
        if tenant_id is None
        else registry.global_root / tenant_id
    )
    return tenant_dir / ".sources_cache" / config.source_id


async def _ingest_with_logging(kernel: MemoryKernel, label: str) -> None:
    """Wrap :meth:`MemoryKernel.ingest_async` with structured logging.

    Never raises — failures are logged so the activate / sync route
    that scheduled this task doesn't crash the event loop.
    """
    try:
        stats = await kernel.ingest_async(force=False)
        try:
            node_count = len(kernel.graph.all_nodes())
        except Exception:  # noqa: BLE001 — graph access shouldn't fail post-ingest
            node_count = -1
        logger.info(
            "kernel re-ingest complete for %s: stats=%s nodes=%d",
            label,
            stats,
            node_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("kernel re-ingest failed for %s: %s", label, exc)


async def swap_kernel_to_source(
    app: "FastAPI", tenant_id: str | None, source_id: str
) -> None:
    """Re-point the single-tenant kernel at the source's vault and reindex.

    Steps:

    1. Resolve the new vault path via :func:`vault_path_for_source`.
       For Local: the source folder. For others: the cache dir.
    2. Build a fresh :class:`MemoryKernel` against that path. The
       kernel constructor wires VaultStorage, indexer, retriever, and
       per-vault caches — re-construction is the cleanest swap.
    3. Replace ``app.state.kernel`` + ``app.state.vault_path``.
    4. Schedule an ``ingest_async`` task so the route returns quickly
       and the graph populates in the background.

    Safe to call when ``source_id`` isn't registered yet (logs and
    returns). Idempotent under concurrent calls — last writer wins on
    ``app.state.kernel``; the previous kernel is just garbage-
    collected.
    """
    registry = getattr(app.state, "source_registry", None)
    if registry is None:
        logger.warning(
            "swap_kernel_to_source called with no source_registry on app.state"
        )
        return
    config = registry.get_config(tenant_id, source_id)
    if config is None:
        logger.warning(
            "swap_kernel_to_source: source %s/%s not registered",
            tenant_id,
            source_id,
        )
        return

    new_vault = vault_path_for_source(config, registry, tenant_id)
    new_vault.mkdir(parents=True, exist_ok=True)
    use_gam = bool(getattr(app.state, "use_gam", True))

    new_kernel = MemoryKernel(vault_path=str(new_vault), use_gam=use_gam)
    app.state.kernel = new_kernel
    app.state.vault_path = str(new_vault)
    logger.info(
        "swapped kernel to source %s/%s -> %s (use_gam=%s)",
        tenant_id,
        source_id,
        new_vault,
        use_gam,
    )

    asyncio.create_task(_ingest_with_logging(new_kernel, f"swap:{source_id}"))


async def reindex_active_kernel(app: "FastAPI", source_id: str) -> None:
    """Re-run ingest on the current kernel without changing its vault.

    Called from the sync path after ``materialize_to_vault`` finishes,
    when the synced source is the active one. For Local sources where
    the source path IS the kernel's vault, materialize is a no-op but
    re-ingest is still useful because external edits to the folder
    (operator drops new ``.md`` files in) need to land in the graph.
    """
    kernel: MemoryKernel | None = getattr(app.state, "kernel", None)
    if kernel is None:
        logger.warning("reindex_active_kernel: no kernel on app.state")
        return
    asyncio.create_task(_ingest_with_logging(kernel, f"sync:{source_id}"))


__all__ = [
    "reindex_active_kernel",
    "swap_kernel_to_source",
    "vault_path_for_source",
]
