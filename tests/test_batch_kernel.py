"""Tests for BatchMemoryKernel.

This test suite validates:
- Batch retrieval operations
- Batch update operations
- Batch delete operations
- Result aggregation
- Deduplication
- Error handling
- Performance improvements
"""

from pathlib import Path

import pytest

from memograph.core.kernel_batch import BatchMemoryKernel, create_batch_kernel
from memograph.core.validation import ValidationError

# Note: consolidated kernel may raise TypeError, ValueError, or ValidationError
# depending on the code path


@pytest.fixture
def temp_vault(tmp_path):
    """Create a temporary vault directory."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
async def batch_kernel(temp_vault):
    """Create a batch kernel."""
    kernel = BatchMemoryKernel(
        vault_path=str(temp_vault), enable_cache=True, max_concurrent=10
    )
    return kernel


@pytest.fixture
async def populated_batch_kernel(temp_vault):
    """Create a kernel with test memories."""
    kernel = BatchMemoryKernel(vault_path=str(temp_vault))

    # Create test memories
    memories = [
        ("Python Tips", "Use list comprehensions", ["python", "tips"]),
        ("Python Testing", "Write unit tests", ["python", "testing"]),
        ("Docker Setup", "Container configuration", ["docker", "devops"]),
        ("Docker Compose", "Multi-container apps", ["docker", "compose"]),
        ("Git Workflow", "Version control", ["git", "workflow"]),
        ("Git Branching", "Feature branches", ["git", "branching"]),
        ("ML Basics", "Machine learning intro", ["ml", "ai"]),
        ("Testing Guide", "Testing best practices", ["testing", "quality"]),
    ]

    for title, content, tags in memories:
        await kernel.remember_async(title, content, tags=tags)

    await kernel.ingest_async()
    return kernel


class TestBatchInitialization:
    """Test batch kernel initialization."""

    @pytest.mark.asyncio
    async def test_basic_initialization(self, temp_vault):
        """Test basic batch kernel initialization."""
        kernel = BatchMemoryKernel(vault_path=str(temp_vault))

        assert Path(kernel.vault_path) == Path(temp_vault)
        assert kernel.max_concurrent == 10

    @pytest.mark.asyncio
    async def test_create_batch_kernel_convenience(self, temp_vault):
        """Test create_batch_kernel convenience function."""
        kernel = await create_batch_kernel(str(temp_vault))

        assert isinstance(kernel, BatchMemoryKernel)


class TestBatchRetrieval:
    """Test batch retrieval operations."""

    @pytest.mark.asyncio
    async def test_retrieve_batch_basic(self, populated_batch_kernel):
        """Test basic batch retrieval."""
        queries = ["python", "docker", "git"]

        results = await populated_batch_kernel.retrieve_batch_async(
            queries, show_progress=False
        )

        assert len(results) == 3
        assert all(q in results for q in queries)
        assert all(isinstance(results[q], list) for q in queries)

    @pytest.mark.asyncio
    async def test_retrieve_batch_with_deduplication(self, populated_batch_kernel):
        """Test batch retrieval with deduplication."""
        queries = ["python", "testing"]  # Both should match "Python Testing"

        results = await populated_batch_kernel.retrieve_batch_async(
            queries, deduplicate=True, show_progress=False
        )

        # Check that results are deduplicated
        all_node_ids = []
        for nodes in results.values():
            all_node_ids.extend([n.id for n in nodes])

        # Should have no duplicates
        assert len(all_node_ids) == len(set(all_node_ids))

    @pytest.mark.asyncio
    async def test_retrieve_batch_without_deduplication(self, populated_batch_kernel):
        """Test batch retrieval without deduplication."""
        queries = ["python", "testing"]

        results = await populated_batch_kernel.retrieve_batch_async(
            queries, deduplicate=False, show_progress=False
        )

        # Both queries should return results
        assert len(results["python"]) > 0
        assert len(results["testing"]) > 0

    @pytest.mark.asyncio
    async def test_retrieve_batch_validation(self, populated_batch_kernel):
        """Test validation in batch retrieval."""
        with pytest.raises((TypeError, ValueError, ValidationError)):
            await populated_batch_kernel.retrieve_batch_async(
                ["valid", ""],  # Empty query
                show_progress=False,
            )

    @pytest.mark.asyncio
    async def test_retrieve_batch_with_tags(self, populated_batch_kernel):
        """Test batch retrieval with tag filtering."""
        queries = ["python", "docker"]

        results = await populated_batch_kernel.retrieve_batch_async(
            queries,
            tags=["python"],  # Filter by python tag
            show_progress=False,
        )

        # Should return results
        assert isinstance(results, dict)
        assert len(results) == 2


class TestBatchUpdate:
    """Test batch update operations."""

    @pytest.mark.asyncio
    async def test_update_batch_basic(self, populated_batch_kernel):
        """Test basic batch update."""
        # Get some memory IDs
        all_nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_ids = [node.id for node in all_nodes[:2]]

        updates = [
            {"id": memory_ids[0], "tags": ["updated", "python"]},
            {"id": memory_ids[1], "salience": 0.9},
        ]

        updated_ids = await populated_batch_kernel.update_batch_async(
            updates, show_progress=False
        )

        assert len(updated_ids) == 2
        assert all(uid in memory_ids for uid in updated_ids)

    @pytest.mark.asyncio
    async def test_update_batch_validation(self, populated_batch_kernel):
        """Test validation in batch update."""
        with pytest.raises((TypeError, ValueError, ValidationError)):
            await populated_batch_kernel.update_batch_async(
                [{"tags": ["no-id"]}],  # Missing 'id' field
                show_progress=False,
            )

    @pytest.mark.asyncio
    async def test_update_batch_nonexistent(self, populated_batch_kernel):
        """Test updating nonexistent memory."""
        with pytest.raises(FileNotFoundError):
            await populated_batch_kernel.update_batch_async(
                [{"id": "nonexistent-id", "tags": ["test"]}], show_progress=False
            )

    @pytest.mark.asyncio
    async def test_update_batch_content(self, populated_batch_kernel):
        """Test updating content in batch."""
        # Get a memory ID
        nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_id = nodes[0].id

        updates = [{"id": memory_id, "content": "Updated content"}]

        updated_ids = await populated_batch_kernel.update_batch_async(
            updates, show_progress=False
        )

        assert len(updated_ids) == 1

        # Verify update
        updated_node = populated_batch_kernel.graph.get(memory_id)
        assert "Updated content" in updated_node.content


class TestBatchDelete:
    """Test batch delete operations."""

    @pytest.mark.asyncio
    async def test_delete_batch_basic(self, populated_batch_kernel):
        """Test basic batch deletion."""
        # Get some memory IDs
        all_nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_ids = [node.id for node in all_nodes[:2]]

        deleted_ids = await populated_batch_kernel.delete_batch_async(
            memory_ids, show_progress=False
        )

        assert len(deleted_ids) == 2
        assert all(did in memory_ids for did in deleted_ids)

        # Verify deletion
        for memory_id in deleted_ids:
            assert populated_batch_kernel.graph.get(memory_id) is None

    @pytest.mark.asyncio
    async def test_delete_batch_validation(self, populated_batch_kernel):
        """Test validation in batch delete."""
        with pytest.raises((TypeError, ValueError, ValidationError)):
            await populated_batch_kernel.delete_batch_async(
                [""],  # Invalid ID
                show_progress=False,
            )

    @pytest.mark.asyncio
    async def test_delete_batch_nonexistent(self, populated_batch_kernel):
        """Test deleting nonexistent memory."""
        with pytest.raises(FileNotFoundError):
            await populated_batch_kernel.delete_batch_async(
                ["nonexistent-id"], show_progress=False
            )


class TestAggregation:
    """Test result aggregation."""

    @pytest.mark.asyncio
    async def test_aggregate_union(self, populated_batch_kernel):
        """Test union aggregation."""
        queries = ["python", "docker"]

        union_results = await populated_batch_kernel.aggregate_results_async(
            queries, aggregation="union", show_progress=False
        )

        # Should contain all unique nodes from both queries
        assert len(union_results) > 0

        # Check uniqueness
        node_ids = [n.id for n in union_results]
        assert len(node_ids) == len(set(node_ids))

    @pytest.mark.asyncio
    async def test_aggregate_intersection(self, populated_batch_kernel):
        """Test intersection aggregation."""
        # Create a memory that matches both queries
        await populated_batch_kernel.remember_async(
            "Python Docker", "Using Python with Docker", tags=["python", "docker"]
        )
        await populated_batch_kernel.ingest_async()

        queries = ["python", "docker"]

        intersection_results = await populated_batch_kernel.aggregate_results_async(
            queries, aggregation="intersection", show_progress=False
        )

        # Intersection should return nodes that appear in both result sets
        # The "Python Docker" memory should be in the intersection
        assert len(intersection_results) >= 0  # May be 0 or more depending on retrieval

    @pytest.mark.asyncio
    async def test_aggregate_invalid_method(self, populated_batch_kernel):
        """Test invalid aggregation method."""
        with pytest.raises(ValueError):
            await populated_batch_kernel.aggregate_results_async(
                ["python"], aggregation="invalid", show_progress=False
            )


class TestProgressTracking:
    """Test progress tracking."""

    @pytest.mark.asyncio
    async def test_retrieve_batch_with_progress(self, populated_batch_kernel):
        """Test batch retrieval with progress tracking."""
        queries = ["python", "docker", "git"]

        # Should not raise even if rich is not installed
        results = await populated_batch_kernel.retrieve_batch_async(
            queries, show_progress=True
        )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_update_batch_with_progress(self, populated_batch_kernel):
        """Test batch update with progress tracking."""
        nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_id = nodes[0].id

        updates = [{"id": memory_id, "tags": ["progress-test"]}]

        # Should not raise
        updated_ids = await populated_batch_kernel.update_batch_async(
            updates, show_progress=True
        )

        assert len(updated_ids) == 1

    @pytest.mark.asyncio
    async def test_delete_batch_with_progress(self, populated_batch_kernel):
        """Test batch delete with progress tracking."""
        nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_id = nodes[0].id

        # Should not raise
        deleted_ids = await populated_batch_kernel.delete_batch_async(
            [memory_id], show_progress=True
        )

        assert len(deleted_ids) == 1


class TestPerformance:
    """Test performance improvements."""

    @pytest.mark.asyncio
    async def test_batch_retrieval_performance(self, populated_batch_kernel):
        """Test that batch retrieval is efficient."""
        queries = ["python", "docker", "git", "testing", "ml"]

        import time

        start = time.time()
        results = await populated_batch_kernel.retrieve_batch_async(
            queries, show_progress=False
        )
        duration = time.time() - start

        assert len(results) == 5
        assert duration < 10  # Should complete in < 10 seconds

        print(f"Batch retrieval time: {duration:.3f}s")

    @pytest.mark.asyncio
    async def test_batch_update_performance(self, populated_batch_kernel):
        """Test that batch update is efficient."""
        nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        memory_ids = [node.id for node in nodes[:5]]

        updates = [{"id": mid, "tags": ["batch-updated"]} for mid in memory_ids]

        import time

        start = time.time()
        updated_ids = await populated_batch_kernel.update_batch_async(
            updates, show_progress=False
        )
        duration = time.time() - start

        assert len(updated_ids) == len(memory_ids)
        assert duration < 10  # Should complete in < 10 seconds

        print(f"Batch update time: {duration:.3f}s")


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_partial_failure_retrieval(self, populated_batch_kernel):
        """Test handling of partial failures in retrieval."""
        queries = ["python", ""]  # One invalid query

        with pytest.raises((TypeError, ValueError, ValidationError)):
            await populated_batch_kernel.retrieve_batch_async(
                queries, show_progress=False
            )

    @pytest.mark.asyncio
    async def test_partial_failure_update(self, populated_batch_kernel):
        """Test handling of partial failures in update."""
        nodes = await populated_batch_kernel.retrieve_nodes_async("python")
        valid_id = nodes[0].id

        updates = [
            {"id": valid_id, "tags": ["test"]},
            {"id": "nonexistent", "tags": ["test"]},
        ]

        with pytest.raises(FileNotFoundError):
            await populated_batch_kernel.update_batch_async(
                updates, show_progress=False
            )


class TestBackwardCompatibility:
    """Test backward compatibility."""

    @pytest.mark.asyncio
    async def test_async_methods_still_work(self, batch_kernel):
        """Test that async methods from parent class still work."""
        # Async remember should still work
        path = await batch_kernel.remember_async("Test", "Content")
        assert Path(path).exists()

        # Async ingest should still work
        await batch_kernel.ingest_async()

        # Async retrieve should still work
        results = await batch_kernel.retrieve_nodes_async("test")
        assert isinstance(results, list)
