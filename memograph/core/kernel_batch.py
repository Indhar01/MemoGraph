"""Backwards-compatibility alias.

BatchMemoryKernel features have been merged into MemoryKernel.
This module re-exports MemoryKernel for existing code.
"""

from memograph.core.kernel import MemoryKernel

# Backwards-compat alias
BatchMemoryKernel = MemoryKernel


async def create_batch_kernel(
    vault_path: str, enable_cache: bool = True, max_concurrent: int = 10, **kwargs
) -> MemoryKernel:
    """Create and initialize a memory kernel with batch support."""
    kernel = MemoryKernel(
        vault_path=vault_path,
        enable_cache=enable_cache,
        max_concurrent=max_concurrent,
        **kwargs,
    )
    await kernel.ingest_async()
    return kernel


__all__ = ["BatchMemoryKernel", "create_batch_kernel"]
