"""Backwards-compatibility alias.

EnhancedMemoryKernel features (caching, validation) have been merged
into MemoryKernel. This module provides a thin wrapper that sets
enable_cache=True and validate_inputs=True by default for backwards compat.
"""

from memograph.core.kernel import MemoryKernel
from memograph.core.validation import MemoGraphError, ValidationError


class EnhancedMemoryKernel(MemoryKernel):
    """Backwards-compat wrapper with caching and validation enabled by default."""

    def __init__(
        self,
        vault_path: str,
        enable_cache: bool = True,
        validate_inputs: bool = True,
        **kwargs,
    ):
        super().__init__(
            vault_path=vault_path,
            enable_cache=enable_cache,
            validate_inputs=validate_inputs,
            **kwargs,
        )


def create_kernel(vault_path: str, enable_cache: bool = True, **kwargs) -> MemoryKernel:
    """Create a memory kernel with caching enabled by default."""
    return EnhancedMemoryKernel(
        vault_path=vault_path, enable_cache=enable_cache, **kwargs
    )


__all__ = ["EnhancedMemoryKernel", "create_kernel", "MemoGraphError", "ValidationError"]
