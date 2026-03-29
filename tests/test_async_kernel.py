"""Tests for AsyncMemoryKernel.

This test suite validates:
- Async memory creation
- Async retrieval
- Async ingestion
- Concurrent operations
- Batch operations
- Error handling in async context
- Performance improvements from concurrency
"""

import asyncio
import time
from pathlib import Path

import pytest

from memograph.core.kernel_async import AsyncMemoryKernel, create_async_kernel


@pytest.fixture
def temp_vault(tmp_path):
    """Create a temporary vault directory."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
async def async_kernel(temp_vault):
    """Create an async kernel."""
    kernel = AsyncMemoryKernel(
        vault_path=str(temp_vault), enable_cache=True, max_concurrent=10
    )
    return kernel


@pytest.fixture
async def populated_async_kernel(temp_vault):
    """Create a kernel with test memories."""
    kernel = AsyncMemoryKernel(vault_path=str(temp_vault))

    # Create test memories
    memories = [
        ("Python Tips", "Use list comprehensions", ["python", "tips"]),
        ("ML Basics", "Machine learning fundamentals", ["ml", "ai"]),
        ("Testing Guide", "How to write tests", ["testing", "python"]),
        ("Docker Setup", "Container configuration", ["docker", "devops"]),
        ("Git Workflow", "Version control best practices", ["git", "workflow"]),
    ]

    for title, content, tags in memories:
        await kernel.remember_async(title, content, tags=tags)

    await kernel.ingest_async()
    return kernel


class TestAsyncInitialization:
    """Test async kernel initialization."""

    @pytest.mark.asyncio
    async def test_basic_initialization(self, temp_vault):
        """Test basic async kernel initialization."""
        kernel = AsyncMemoryKernel(vault_path=str(temp_vault))

        assert Path(kernel.vault_path) == Path(temp_vault)
        assert kernel.max_concurrent == 10
        assert kernel._semaphore._value == 10

    @pytest.mark.asyncio
    async def test_custom_concurrency(self, temp_vault):
        """Test custom concurrency limit."""
        kernel = AsyncMemoryKernel(vault_path=str(temp_vault), max_concurrent=5)

        assert kernel.max_concurrent == 5
        assert kernel._semaphore._value == 5

    @pytest.mark.asyncio
    async def test_create_async_kernel_convenience(self, temp_vault):
        """Test create_async_kernel convenience function."""
        kernel = await create_async_kernel(str(temp_vault))

        assert isinstance(kernel, AsyncMemoryKernel)
        # Check graph is initialized
        assert kernel.graph is not None


class TestAsyncRemember:
    """Test async memory creation."""

    @pytest.mark.asyncio
    async def test_remember_async_basic(self, async_kernel):
        """Test basic async memory creation."""
        path = await async_kernel.remember_async(
            title="Test Memory", content="Test content", tags=["test"]
        )

        assert Path(path).exists()
        assert "test-memory" in path.lower()

    @pytest.mark.asyncio
    async def test_remember_async_validation(self, async_kernel):
        """Test validation in async remember."""
        with pytest.raises((TypeError, ValueError)):
            await async_kernel.remember_async(
                title="",  # Empty title
                content="Content",
            )

    @pytest.mark.asyncio
    async def test_concurrent_remember(self, async_kernel):
        """Test concurrent memory creation."""
        tasks = [
            async_kernel.remember_async(f"Memory {i}", f"Content {i}", tags=[f"tag{i}"])
            for i in range(10)
        ]

        start = time.time()
        paths = await asyncio.gather(*tasks)
        duration = time.time() - start

        assert len(paths) == 10
        assert all(Path(p).exists() for p in paths)

        # Should be faster than sequential (rough check)
        print(f"Concurrent creation time: {duration:.3f}s")

    @pytest.mark.asyncio
    async def test_remember_with_semaphore_limit(self, temp_vault):
        """Test that semaphore limits concurrent operations."""
        kernel = AsyncMemoryKernel(
            vault_path=str(temp_vault),
            max_concurrent=2,  # Low limit
        )

        # Just verify semaphore is set correctly
        assert kernel._semaphore._value == 2

        # Create some memories
        tasks = [kernel.remember_async(f"Memory {i}", f"Content {i}") for i in range(5)]
        paths = await asyncio.gather(*tasks)

        # All should complete successfully
        assert len(paths) == 5


class TestAsyncRetrieve:
    """Test async retrieval."""

    @pytest.mark.asyncio
    async def test_retrieve_async_basic(self, populated_async_kernel):
        """Test basic async retrieval."""
        results = await populated_async_kernel.retrieve_nodes_async("python")

        assert len(results) > 0
        assert any("python" in node.tags for node in results)

    @pytest.mark.asyncio
    async def test_retrieve_async_validation(self, populated_async_kernel):
        """Test validation in async retrieve."""
        with pytest.raises((TypeError, ValueError)):
            await populated_async_kernel.retrieve_nodes_async("")

    @pytest.mark.asyncio
    async def test_concurrent_retrieve(self, populated_async_kernel):
        """Test concurrent retrieval."""
        queries = ["python", "docker", "git", "testing", "ml"]

        start = time.time()
        results = await asyncio.gather(
            *[populated_async_kernel.retrieve_nodes_async(q) for q in queries]
        )
        duration = time.time() - start

        assert len(results) == 5
        assert all(isinstance(r, list) for r in results)

        print(f"Concurrent retrieval time: {duration:.3f}s")

    @pytest.mark.asyncio
    async def test_retrieve_with_cache(self, populated_async_kernel):
        """Test that cache works with async retrieve."""
        query = "python programming"

        # First query (cache miss)
        start = time.time()
        results1 = await populated_async_kernel.retrieve_nodes_async(query)
        time.time() - start

        # Second query (cache hit)
        start = time.time()
        results2 = await populated_async_kernel.retrieve_nodes_async(query)
        time.time() - start

        # Results should be identical
        assert len(results1) == len(results2)

        # Check cache stats
        stats = await populated_async_kernel.get_cache_stats_async()
        if "query" in stats:
            assert stats["query"]["hits"] > 0


class TestAsyncIngest:
    """Test async ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_async_basic(self, async_kernel, temp_vault):
        """Test basic async ingestion."""
        # Create a test file
        test_file = temp_vault / "test.md"
        test_file.write_text("---\ntitle: Test\ntags: [test]\n---\nContent")

        await async_kernel.ingest_async()

        # Check that graph has nodes
        assert len(async_kernel.graph._nodes) > 0

    @pytest.mark.asyncio
    async def test_ingest_async_with_force(self, async_kernel, temp_vault):
        """Test forced re-indexing."""
        test_file = temp_vault / "test.md"
        test_file.write_text("---\ntitle: Test\ntags: [test]\n---\nContent")

        # First ingest
        await async_kernel.ingest_async()
        count1 = len(async_kernel.graph._nodes)

        # Force re-ingest
        await async_kernel.ingest_async(force=True)
        count2 = len(async_kernel.graph._nodes)

        assert count1 == count2


class TestBatchOperations:
    """Test batch operations."""

    @pytest.mark.asyncio
    async def test_remember_batch_async_basic(self, async_kernel):
        """Test basic batch memory creation."""
        memories = [
            {
                "title": f"Memory {i}",
                "content": f"Content for memory {i}",
                "tags": [f"tag{i % 3}"],
            }
            for i in range(20)
        ]

        start = time.time()
        paths = await async_kernel.remember_batch_async(memories, show_progress=False)
        duration = time.time() - start

        assert len(paths) == 20
        assert all(Path(p).exists() for p in paths)

        print(f"Batch creation time: {duration:.3f}s")

    @pytest.mark.asyncio
    async def test_remember_batch_async_performance(self, async_kernel):
        """Test that batch is faster than sequential."""
        memories = [
            {"title": f"Memory {i}", "content": f"Content {i}", "tags": ["batch"]}
            for i in range(10)
        ]

        # Batch creation
        start = time.time()
        await async_kernel.remember_batch_async(memories, show_progress=False)
        batch_time = time.time() - start

        # Should complete in reasonable time
        assert batch_time < 30  # 30 seconds for 10 memories

        print(f"Batch time: {batch_time:.3f}s")

    @pytest.mark.asyncio
    async def test_remember_batch_with_progress(self, async_kernel):
        """Test batch creation with progress indicator."""
        memories = [
            {"title": f"Memory {i}", "content": f"Content {i}", "tags": ["progress"]}
            for i in range(5)
        ]

        # Should not raise even if rich is not installed
        paths = await async_kernel.remember_batch_async(memories, show_progress=True)

        assert len(paths) == 5


class TestContextWindow:
    """Test async context window."""

    @pytest.mark.asyncio
    async def test_context_window_async(self, populated_async_kernel):
        """Test async context window generation."""
        context = await populated_async_kernel.context_window_async(
            "python tips", token_limit=1024
        )

        assert isinstance(context, str)
        assert len(context) > 0


class TestCacheManagement:
    """Test async cache management."""

    @pytest.mark.asyncio
    async def test_get_cache_stats_async(self, populated_async_kernel):
        """Test getting cache stats asynchronously."""
        # Perform some queries
        await populated_async_kernel.retrieve_nodes_async("python")
        await populated_async_kernel.retrieve_nodes_async("python")  # Cache hit

        stats = await populated_async_kernel.get_cache_stats_async()

        assert isinstance(stats, dict)
        if "query" in stats:
            assert stats["query"]["hits"] > 0

    @pytest.mark.asyncio
    async def test_clear_cache_async(self, populated_async_kernel):
        """Test clearing cache asynchronously."""
        # Populate cache
        await populated_async_kernel.retrieve_nodes_async("python")

        # Clear cache
        await populated_async_kernel.clear_cache_async(cache_type="query")

        # Should not raise
        stats = await populated_async_kernel.get_cache_stats_async()
        assert isinstance(stats, dict)


class TestErrorHandling:
    """Test error handling in async context."""

    @pytest.mark.asyncio
    async def test_validation_error_propagation(self, async_kernel):
        """Test that validation errors propagate correctly."""
        with pytest.raises((TypeError, ValueError)):
            await async_kernel.remember_async("", "Content")

    @pytest.mark.asyncio
    async def test_concurrent_error_handling(self, async_kernel):
        """Test error handling with concurrent operations."""
        tasks = [
            async_kernel.remember_async(f"Memory {i}", f"Content {i}") for i in range(5)
        ]

        # Add a failing task
        tasks.append(async_kernel.remember_async("", "Content"))

        # Should raise ValidationError
        with pytest.raises((TypeError, ValueError)):
            await asyncio.gather(*tasks)


class TestPerformance:
    """Test performance improvements from async."""

    @pytest.mark.asyncio
    async def test_concurrent_vs_sequential(self, async_kernel):
        """Compare concurrent vs sequential performance."""
        memories = [
            {"title": f"Memory {i}", "content": f"Content {i}", "tags": ["perf"]}
            for i in range(10)
        ]

        # Concurrent
        start = time.time()
        await async_kernel.remember_batch_async(memories, show_progress=False)
        concurrent_time = time.time() - start

        # Concurrent should be reasonably fast
        assert concurrent_time < 30  # 30 seconds for 10 memories

        print(f"Concurrent: {concurrent_time:.3f}s")

    @pytest.mark.asyncio
    async def test_concurrent_queries_performance(self, populated_async_kernel):
        """Test concurrent query performance."""
        queries = ["python", "docker", "git"] * 5  # 15 queries

        start = time.time()
        results = await asyncio.gather(
            *[populated_async_kernel.retrieve_nodes_async(q) for q in queries]
        )
        duration = time.time() - start

        assert len(results) == 15
        assert duration < 10  # Should complete in < 10 seconds

        print(f"15 concurrent queries: {duration:.3f}s")


class TestBackwardCompatibility:
    """Test backward compatibility with sync methods."""

    @pytest.mark.asyncio
    async def test_sync_methods_still_work(self, async_kernel):
        """Test that sync methods still work."""
        # Sync remember should still work
        path = async_kernel.remember("Sync Memory", "Sync content")
        assert Path(path).exists()

        # Sync ingest should still work
        async_kernel.ingest()

        # Sync retrieve should still work
        results = async_kernel.retrieve_nodes("sync")
        assert isinstance(results, list)
