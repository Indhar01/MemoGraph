"""
Stress tests for async operations with large vaults and concurrent operations.

Run with: pytest tests/stress/test_stress_async.py -v -s
Run all stress tests: pytest -m stress
"""

import asyncio
import logging
import time
from pathlib import Path

import pytest

from memograph.core.kernel_gam_async import create_gam_async_kernel

# Configure logging for stress tests
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("memograph.stress")


@pytest.mark.stress
@pytest.mark.slow
class TestLargeVaultPerformance:
    """Test performance with large vaults (1000+ memories)."""

    @pytest.mark.asyncio
    async def test_1000_memories_creation(self, tmp_path: Path):
        """Test creating 1000 memories with batch operations."""
        logger.info("Starting 1000 memory creation test")

        vault = tmp_path / "large_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=20)

        # Create 1000 memories
        memories = [
            {
                "title": f"Memory {i}",
                "content": f"This is test content for memory {i}. " * 20,
                "tags": [f"tag{i % 10}", f"category{i % 5}", "stress-test"],
            }
            for i in range(1000)
        ]

        start_time = time.time()
        paths = await kernel.remember_batch_async(memories, show_progress=True)
        create_time = time.time() - start_time

        assert len(paths) == 1000
        assert create_time < 60, f"Creation took {create_time:.2f}s, expected <60s"

        logger.info(f"Created 1000 memories in {create_time:.2f}s")
        logger.info(f"Average: {create_time / 1000 * 1000:.2f}ms per memory")

        # Ingest
        start_time = time.time()
        await kernel.ingest_async(force=True)
        ingest_time = time.time() - start_time

        assert ingest_time < 30, f"Ingest took {ingest_time:.2f}s, expected <30s"
        logger.info(f"Ingested vault in {ingest_time:.2f}s")

    @pytest.mark.asyncio
    async def test_1000_memories_query_performance(self, tmp_path: Path):
        """Test query performance on vault with 1000 memories."""
        logger.info("Starting 1000 memory query performance test")

        vault = tmp_path / "query_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=20)

        # Create 1000 memories with varied content
        memories = [
            {
                "title": f"Memory about {topic}",
                "content": f"Detailed information about {topic}. " * 30,
                "tags": [topic, f"category{i % 10}"],
            }
            for i, topic in enumerate(
                ["python", "docker", "kubernetes", "fastapi", "react"] * 200
            )
        ]

        await kernel.remember_batch_async(memories, show_progress=True)
        await kernel.ingest_async(force=True)

        # Test single query performance
        start_time = time.time()
        results = await kernel.retrieve_nodes_async("python programming", top_k=10)
        query_time = time.time() - start_time

        assert len(results) > 0
        assert query_time < 2.0, f"Query took {query_time:.3f}s, expected <2.0s"
        logger.info(f"Single query: {query_time * 1000:.2f}ms")

        # Test multiple sequential queries
        queries = ["python", "docker", "kubernetes", "fastapi", "react"]
        start_time = time.time()

        for query in queries:
            results = await kernel.retrieve_nodes_async(query, top_k=5)
            assert len(results) > 0

        sequential_time = time.time() - start_time
        logger.info(f"Sequential queries (5): {sequential_time:.2f}s")

        # Test concurrent queries
        start_time = time.time()
        results = await asyncio.gather(
            *[kernel.retrieve_nodes_async(q, top_k=5) for q in queries]
        )
        concurrent_time = time.time() - start_time

        assert len(results) == len(queries)
        assert concurrent_time < sequential_time * 0.7, (
            f"Concurrent ({concurrent_time:.2f}s) not faster than sequential ({sequential_time:.2f}s)"
        )

        logger.info(f"Concurrent queries (5): {concurrent_time:.2f}s")
        logger.info(f"Speedup: {sequential_time / concurrent_time:.2f}x")


@pytest.mark.stress
@pytest.mark.slow
class TestConcurrentOperations:
    """Test concurrent operations and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_writes(self, tmp_path: Path):
        """Test concurrent memory creation."""
        logger.info("Starting concurrent writes test")

        vault = tmp_path / "concurrent_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=50)

        # Create memories concurrently
        async def create_memory(index: int) -> str:
            return await kernel.remember_async(
                f"Concurrent Memory {index}",
                f"Content for memory {index}",
                tags=["concurrent", f"batch{index % 10}"],
            )

        start_time = time.time()
        paths = await asyncio.gather(*[create_memory(i) for i in range(100)])
        duration = time.time() - start_time

        assert len(paths) == 100
        assert len(set(paths)) == 100, "Duplicate paths detected"
        assert duration < 20, f"Took {duration:.2f}s, expected <20s"

        logger.info(f"Created 100 memories concurrently in {duration:.2f}s")
        logger.info(f"Average: {duration / 100 * 1000:.2f}ms per memory")

    @pytest.mark.asyncio
    async def test_concurrent_reads(self, tmp_path: Path):
        """Test concurrent query operations."""
        logger.info("Starting concurrent reads test")

        vault = tmp_path / "read_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=50)

        # Create test data
        memories = [
            {
                "title": f"Document {i}",
                "content": f"Content about topic {i % 5}",
                "tags": [f"topic{i % 5}", "test"],
            }
            for i in range(100)
        ]

        await kernel.remember_batch_async(memories)
        await kernel.ingest_async()

        # Perform 50 concurrent queries
        queries = [f"topic {i % 5}" for i in range(50)]

        start_time = time.time()
        results = await asyncio.gather(
            *[kernel.retrieve_nodes_async(q, top_k=5) for q in queries]
        )
        duration = time.time() - start_time

        assert len(results) == 50
        # Allow some queries to have empty results due to timing/indexing
        non_empty = sum(1 for r in results if len(r) > 0)
        assert non_empty > 45, f"Only {non_empty}/50 queries returned results"
        assert duration < 10, f"Took {duration:.2f}s, expected <10s"

        logger.info(f"Executed 50 concurrent queries in {duration:.2f}s")
        logger.info(f"Average: {duration / 50 * 1000:.2f}ms per query")

    @pytest.mark.asyncio
    async def test_mixed_workload(self, tmp_path: Path):
        """Test mixed read/write workload."""
        logger.info("Starting mixed workload test")

        vault = tmp_path / "mixed_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=30)

        # Create initial data
        initial_memories = [
            {
                "title": f"Initial {i}",
                "content": f"Initial content {i}",
                "tags": ["initial"],
            }
            for i in range(50)
        ]
        await kernel.remember_batch_async(initial_memories)
        await kernel.ingest_async()

        # Mixed operations
        async def mixed_operations():
            operations = []

            # Add writes
            for i in range(20):
                operations.append(
                    kernel.remember_async(
                        f"New Memory {i}", f"New content {i}", tags=["new"]
                    )
                )

            # Add reads
            for i in range(30):
                operations.append(
                    kernel.retrieve_nodes_async(f"content {i % 10}", top_k=5)
                )

            return await asyncio.gather(*operations)

        start_time = time.time()
        results = await mixed_operations()
        duration = time.time() - start_time

        assert len(results) == 50
        assert duration < 15, f"Took {duration:.2f}s, expected <15s"

        logger.info(f"Executed 50 mixed operations in {duration:.2f}s")


@pytest.mark.stress
@pytest.mark.slow
class TestMemoryUsage:
    """Test memory usage and leak detection."""

    @pytest.mark.asyncio
    async def test_memory_stability(self, tmp_path: Path):
        """Test memory usage remains stable over many operations."""
        logger.info("Starting memory stability test")

        try:
            import os

            import psutil
        except ImportError:
            pytest.skip("psutil not installed")

        vault = tmp_path / "memory_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=20)

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        logger.info(f"Initial memory: {initial_memory:.2f}MB")

        # Create and query memories in batches
        for batch in range(5):
            memories = [
                {
                    "title": f"Batch {batch} Memory {i}",
                    "content": f"Content for batch {batch} memory {i}" * 20,
                    "tags": [f"batch{batch}"],
                }
                for i in range(100)
            ]

            await kernel.remember_batch_async(memories)
            await kernel.ingest_async(force=True)

            # Perform queries
            await asyncio.gather(
                *[
                    kernel.retrieve_nodes_async(f"batch {batch}", top_k=10)
                    for _ in range(10)
                ]
            )

            current_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"After batch {batch}: {current_memory:.2f}MB")

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_increase = final_memory - initial_memory

        logger.info(f"Final memory: {final_memory:.2f}MB")
        logger.info(f"Memory increase: {memory_increase:.2f}MB")

        # Should not use more than 300MB for 500 memories
        assert memory_increase < 300, (
            f"Memory increased by {memory_increase:.2f}MB, expected <300MB"
        )
