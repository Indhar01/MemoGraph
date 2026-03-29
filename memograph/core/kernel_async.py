"""Async extensions for MemoryKernel.

This module provides async/await support for MemoryKernel operations,
enabling concurrent memory operations and improved performance for
I/O-bound tasks.

Example:
    >>> import asyncio
    >>> from memograph.core.kernel_async import AsyncMemoryKernel
    >>>
    >>> async def main():
    ...     kernel = AsyncMemoryKernel(vault_path="./vault")
    ...     await kernel.ingest_async()
    ...
    ...     # Concurrent memory creation
    ...     tasks = [
    ...         kernel.remember_async("Title 1", "Content 1"),
    ...         kernel.remember_async("Title 2", "Content 2"),
    ...         kernel.remember_async("Title 3", "Content 3")
    ...     ]
    ...     paths = await asyncio.gather(*tasks)
    ...
    ...     # Concurrent retrieval
    ...     results = await kernel.retrieve_nodes_async("query")
    >>>
    >>> asyncio.run(main())
"""

import asyncio
import logging
from typing import Any

from memograph.core.kernel_enhanced import EnhancedMemoryKernel
from memograph.core.node import MemoryNode

logger = logging.getLogger("memograph.async")


class AsyncMemoryKernel(EnhancedMemoryKernel):
    """Async-enabled memory kernel with concurrent operation support.

    This kernel extends EnhancedMemoryKernel with async/await support,
    allowing for concurrent memory operations and improved performance
    for I/O-bound tasks like embedding generation and file operations.

    Features:
    - Async memory creation and retrieval
    - Concurrent batch operations
    - Async embedding generation
    - Non-blocking I/O operations
    - Semaphore-based concurrency control

    Example:
        >>> import asyncio
        >>>
        >>> async def example():
        ...     kernel = AsyncMemoryKernel(
        ...         vault_path="./vault",
        ...         max_concurrent=10
        ...     )
        ...     await kernel.ingest_async()
        ...
        ...     # Create memories concurrently
        ...     memories = [
        ...         {"title": f"Memory {i}", "content": f"Content {i}"}
        ...         for i in range(100)
        ...     ]
        ...     paths = await kernel.remember_batch_async(memories)
        ...
        ...     # Query concurrently
        ...     queries = ["python", "docker", "kubernetes"]
        ...     results = await asyncio.gather(*[
        ...         kernel.retrieve_nodes_async(q) for q in queries
        ...     ])
        >>>
        >>> asyncio.run(example())
    """

    def __init__(self, vault_path: str, max_concurrent: int = 10, **kwargs):
        """Initialize async kernel.

        Args:
            vault_path: Path to vault directory
            max_concurrent: Maximum concurrent operations
            **kwargs: Additional arguments for EnhancedMemoryKernel
        """
        super().__init__(vault_path=vault_path, **kwargs)
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(
            f"AsyncMemoryKernel initialized with max_concurrent={max_concurrent}"
        )

    async def remember_async(  # type: ignore[override]
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        salience: float = 0.5,
        **kwargs,
    ) -> str:
        """Create a new memory asynchronously.

        This method creates a memory without blocking the event loop,
        allowing other async operations to proceed concurrently.

        Args:
            title: Memory title
            content: Memory content
            tags: List of tags
            salience: Salience score (0.0-1.0)
            **kwargs: Additional arguments

        Returns:
            Path to created memory file

        Raises:
            ValidationError: If inputs are invalid

        Example:
            >>> async def create_memory():
            ...     kernel = AsyncMemoryKernel(vault_path="./vault")
            ...     path = await kernel.remember_async(
            ...         "Python Tips",
            ...         "Use type hints for better code",
            ...         tags=["python", "tips"]
            ...     )
            ...     print(f"Created: {path}")
        """
        async with self._semaphore:
            # Run synchronous remember in thread pool
            path = await asyncio.to_thread(
                super().remember, title, content, tags=tags, salience=salience, **kwargs
            )
            logger.debug(f"Created memory async: {title}")
            return path

    async def retrieve_nodes_async(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        use_cache: bool = True,
        **kwargs,
    ) -> list[MemoryNode]:
        """Retrieve memory nodes asynchronously.

        This method performs retrieval without blocking the event loop,
        allowing concurrent queries to be processed efficiently.

        Args:
            query: Search query
            tags: Filter by tags
            depth: Graph traversal depth
            top_k: Number of results to return
            use_cache: Whether to use query cache
            **kwargs: Additional arguments

        Returns:
            List of relevant memory nodes

        Raises:
            ValidationError: If inputs are invalid

        Example:
            >>> async def search():
            ...     kernel = AsyncMemoryKernel(vault_path="./vault")
            ...     await kernel.ingest_async()
            ...
            ...     # Concurrent queries
            ...     results = await asyncio.gather(
            ...         kernel.retrieve_nodes_async("python"),
            ...         kernel.retrieve_nodes_async("docker"),
            ...         kernel.retrieve_nodes_async("kubernetes")
            ...     )
            ...     for i, result in enumerate(results):
            ...         print(f"Query {i}: {len(result)} results")
        """
        async with self._semaphore:
            # Run synchronous retrieve in thread pool
            results = await asyncio.to_thread(
                super().retrieve_nodes,
                query,
                tags=tags,
                depth=depth,
                top_k=top_k,
                use_cache=use_cache,
                **kwargs,
            )
            logger.debug(f"Retrieved {len(results)} nodes async for: {query}")
            return results

    async def ingest_async(self, force: bool = False, show_progress: bool = True):
        """Ingest vault asynchronously.

        This method indexes the vault without blocking the event loop,
        allowing other operations to proceed during indexing.

        Args:
            force: Force re-indexing
            show_progress: Show progress indicator

        Example:
            >>> async def setup():
            ...     kernel = AsyncMemoryKernel(vault_path="./vault")
            ...     await kernel.ingest_async()
            ...     print("Vault indexed!")
        """
        # Run synchronous ingest in thread pool
        await asyncio.to_thread(
            super().ingest, force=force, show_progress=show_progress
        )
        logger.info("Vault ingested async")

    async def remember_batch_async(
        self, memories: list[dict[str, Any]], show_progress: bool = True
    ) -> list[str]:
        """Create multiple memories concurrently.

        This method creates memories in parallel up to max_concurrent limit,
        providing significant speedup over sequential creation.

        Args:
            memories: List of memory dicts with title, content, tags
            show_progress: Show progress indicator

        Returns:
            List of created file paths

        Example:
            >>> async def batch_create():
            ...     kernel = AsyncMemoryKernel(vault_path="./vault")
            ...
            ...     memories = [
            ...         {
            ...             "title": f"Memory {i}",
            ...             "content": f"Content for memory {i}",
            ...             "tags": ["batch", f"group{i % 10}"]
            ...         }
            ...         for i in range(100)
            ...     ]
            ...
            ...     paths = await kernel.remember_batch_async(memories)
            ...     print(f"Created {len(paths)} memories")
        """
        if show_progress:
            try:
                from rich.progress import Progress

                with Progress() as progress:
                    task = progress.add_task(
                        "[cyan]Creating memories...", total=len(memories)
                    )

                    async def create_with_progress(memory: dict[str, Any]) -> str:
                        path = await self.remember_async(
                            title=memory["title"],
                            content=memory["content"],
                            tags=memory.get("tags", []),
                            salience=memory.get("salience", 0.5),
                        )
                        progress.update(task, advance=1)
                        return path

                    paths = await asyncio.gather(
                        *[create_with_progress(m) for m in memories]
                    )
            except ImportError:
                # Fallback without progress bar
                paths = await asyncio.gather(
                    *[
                        self.remember_async(
                            title=m["title"],
                            content=m["content"],
                            tags=m.get("tags", []),
                            salience=m.get("salience", 0.5),
                        )
                        for m in memories
                    ]
                )
        else:
            paths = await asyncio.gather(
                *[
                    self.remember_async(
                        title=m["title"],
                        content=m["content"],
                        tags=m.get("tags", []),
                        salience=m.get("salience", 0.5),
                    )
                    for m in memories
                ]
            )

        # Ingest once after all creates
        await self.ingest_async(force=True, show_progress=False)

        logger.info(f"Created {len(paths)} memories in batch")
        return paths

    async def context_window_async(
        self, query: str, token_limit: int = 2048, **kwargs
    ) -> str:
        """Retrieve context window asynchronously.

        Args:
            query: Search query
            token_limit: Maximum tokens in output
            **kwargs: Additional arguments

        Returns:
            Compressed context string

        Example:
            >>> async def get_context():
            ...     kernel = AsyncMemoryKernel(vault_path="./vault")
            ...     await kernel.ingest_async()
            ...     context = await kernel.context_window_async(
            ...         "python tips",
            ...         token_limit=1024
            ...     )
            ...     print(context)
        """
        async with self._semaphore:
            context = await asyncio.to_thread(
                super().context_window, query, token_limit=token_limit, **kwargs
            )
            return context

    async def get_cache_stats_async(self) -> dict:
        """Get cache statistics asynchronously.

        Returns:
            Dictionary with cache statistics
        """
        return await asyncio.to_thread(super().get_cache_stats)

    async def clear_cache_async(self, cache_type: str = "all"):
        """Clear caches asynchronously.

        Args:
            cache_type: Type of cache to clear ('embedding', 'query', 'all')
        """
        await asyncio.to_thread(super().clear_cache, cache_type)
        logger.info(f"Cache cleared async: {cache_type}")


# Convenience function
async def create_async_kernel(
    vault_path: str, enable_cache: bool = True, max_concurrent: int = 10, **kwargs
) -> AsyncMemoryKernel:
    """Create and initialize an async memory kernel.

    Args:
        vault_path: Path to vault directory
        enable_cache: Whether to enable caching
        max_concurrent: Maximum concurrent operations
        **kwargs: Additional arguments for AsyncMemoryKernel

    Returns:
        Initialized AsyncMemoryKernel instance

    Example:
        >>> async def setup():
        ...     kernel = await create_async_kernel("./vault")
        ...     await kernel.ingest_async()
        ...     return kernel
    """
    kernel = AsyncMemoryKernel(
        vault_path=vault_path,
        enable_cache=enable_cache,
        max_concurrent=max_concurrent,
        **kwargs,
    )
    await kernel.ingest_async()
    return kernel
