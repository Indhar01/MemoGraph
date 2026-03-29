"""Backwards-compatibility alias.

GAMAsyncKernel features have been merged into MemoryKernel.
This module provides a thin wrapper that maps the old `enable_gam`
parameter to `use_gam` and exposes GAM-specific attributes.
"""

from typing import Any

from memograph.core.kernel import MemoryKernel


class GAMAsyncKernel(MemoryKernel):
    """Backwards-compat wrapper mapping enable_gam to use_gam."""

    def __init__(
        self,
        vault_path: str,
        enable_gam: bool = False,
        gam_config: dict[str, Any] | None = None,
        **kwargs,
    ):
        from memograph.core.gam_scorer import GAMConfig

        gam_config_obj = None
        if gam_config and isinstance(gam_config, dict):
            gam_config_obj = GAMConfig(**gam_config)
        elif isinstance(gam_config, GAMConfig):
            gam_config_obj = gam_config

        super().__init__(
            vault_path=vault_path,
            use_gam=enable_gam,
            gam_config=gam_config_obj,
            **kwargs,
        )

        # Store original gam_config dict for backwards compat
        self.gam_config = gam_config if gam_config is not None else {}  # type: ignore[assignment]

        # Expose GAM components as instance attributes for backwards compat
        if enable_gam:
            from memograph.core.access_tracker import AccessTracker
            from memograph.core.gam_scorer import GAMScorer

            self.access_tracker = getattr(self.retriever, "access_tracker", None)
            if self.access_tracker is None:
                self.access_tracker = AccessTracker()
            self.gam_scorer = getattr(self.retriever, "gam_scorer", None)
            if self.gam_scorer is None:
                config_obj = gam_config_obj or GAMConfig()
                self.gam_scorer = GAMScorer(config=config_obj)
            self.gam_retriever = self.retriever
        else:
            self.access_tracker = None  # type: ignore[assignment]
            self.gam_scorer = None  # type: ignore[assignment]
            self.gam_retriever = None  # type: ignore[assignment]


async def create_gam_async_kernel(
    vault_path: str,
    enable_cache: bool = True,
    enable_gam: bool = True,
    max_concurrent: int = 10,
    gam_config: dict[str, Any] | None = None,
    **kwargs,
) -> GAMAsyncKernel:
    """Create and initialize a GAM-enabled memory kernel."""
    kernel = GAMAsyncKernel(
        vault_path=vault_path,
        enable_cache=enable_cache,
        enable_gam=enable_gam,
        gam_config=gam_config,
        max_concurrent=max_concurrent,
        **kwargs,
    )
    await kernel.ingest_async()
    return kernel


__all__ = ["GAMAsyncKernel", "create_gam_async_kernel"]
