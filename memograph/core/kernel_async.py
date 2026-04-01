"""Backwards-compatibility alias.

AsyncMemoryKernel features (async methods, semaphore) have been merged
into MemoryKernel. This module re-exports MemoryKernel for existing code.
"""

from memograph.core.kernel import MemoryKernel

# Backwards-compat alias
AsyncMemoryKernel = MemoryKernel


async def create_async_kernel(
    vault_path: str, enable_cache: bool = True, max_concurrent: int = 10, **kwargs
) -> MemoryKernel:
    """Create and initialize a memory kernel with async support."""
    kernel = MemoryKernel(
        vault_path=vault_path,
        enable_cache=enable_cache,
        max_concurrent=max_concurrent,
        **kwargs,
    )
    await kernel.ingest_async()
    return kernel


__all__ = ["AsyncMemoryKernel", "create_async_kernel"]
