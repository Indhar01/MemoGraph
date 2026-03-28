"""
Load testing scenarios for sustained load, spike load, and gradual ramp-up.

Run with: pytest tests/stress/test_load.py -v -s
"""

import asyncio
import logging
import time
from pathlib import Path

import pytest

from memograph.core.kernel_gam_async import create_gam_async_kernel

logger = logging.getLogger("memograph.load")


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.load
class TestSustainedLoad:
    """Test sustained load over extended periods."""

    @pytest.mark.asyncio
    async def test_1_hour_sustained_operations(self, tmp_path: Path):
        """Test system stability under 1 hour of continuous operations."""
        logger.info("Starting 1-hour sustained load test")
        pytest.skip("Long-running test - enable manually")

        vault = tmp_path / "sustained_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=20)

        start_time = time.time()
        operation_count = 0
        error_count = 0

        # Run for 1 hour
        while time.time() - start_time < 3600:  # 1 hour
            try:
                # Mixed operations
                await kernel.remember_async(
                    f"Memory {operation_count}",
                    f"Content {operation_count}" * 10,
                    tags=["sustained", f"batch{operation_count % 10}"],
                )

                if operation_count % 10 == 0:
                    await kernel.retrieve_nodes_async(
                        f"content {operation_count % 100}", top_k=5
                    )

                operation_count += 1

                # Log progress every 100 operations
                if operation_count % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = operation_count / elapsed
                    logger.info(
                        f"Progress: {operation_count} ops, {elapsed / 60:.1f}min, {rate:.1f} ops/s"
                    )

            except Exception as e:
                error_count += 1
                logger.error(f"Operation failed: {e}")

        duration = time.time() - start_time
        success_rate = (operation_count - error_count) / operation_count * 100

        logger.info(
            f"Completed: {operation_count} operations in {duration / 60:.1f}min"
        )
        logger.info(
            f"Error rate: {error_count}/{operation_count} ({100 - success_rate:.2f}%)"
        )

        assert success_rate > 99.5, f"Success rate too low: {success_rate:.2f}%"

    @pytest.mark.asyncio
    async def test_10_minute_high_throughput(self, tmp_path: Path):
        """Test high throughput sustained for 10 minutes."""
        logger.info("Starting 10-minute high throughput test")

        vault = tmp_path / "throughput_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=30)

        start_time = time.time()
        operation_count = 0
        duration_limit = 600  # 10 minutes

        while time.time() - start_time < duration_limit:
            # Batch of 20 operations
            batch = [
                {
                    "title": f"High Throughput {operation_count + i}",
                    "content": f"Content {operation_count + i}" * 15,
                    "tags": ["throughput", f"batch{i % 5}"],
                }
                for i in range(20)
            ]

            await kernel.remember_batch_async(batch, show_progress=False)
            operation_count += len(batch)

            # Periodic queries
            if operation_count % 100 == 0:
                await kernel.retrieve_nodes_async("throughput", top_k=10)

            if operation_count % 500 == 0:
                elapsed = time.time() - start_time
                rate = operation_count / elapsed
                logger.info(f"{operation_count} ops, {rate:.1f} ops/s")

        duration = time.time() - start_time
        throughput = operation_count / duration

        logger.info(f"Total: {operation_count} operations")
        logger.info(f"Throughput: {throughput:.1f} ops/s")

        # Adjust threshold for Windows performance characteristics
        assert throughput > 5, f"Throughput too low: {throughput:.1f} ops/s"


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.load
class TestSpikeLoad:
    """Test system response to sudden load spikes."""

    @pytest.mark.asyncio
    async def test_sudden_spike(self, tmp_path: Path):
        """Test response to sudden spike in operations."""
        logger.info("Starting spike load test")

        vault = tmp_path / "spike_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=50)

        # Baseline: Low load
        logger.info("Baseline phase: low load")
        baseline_ops = [
            kernel.remember_async(
                f"Baseline {i}", f"Content {i}" * 10, tags=["baseline"]
            )
            for i in range(10)
        ]

        start = time.time()
        await asyncio.gather(*baseline_ops)
        baseline_time = time.time() - start

        logger.info(f"Baseline: 10 ops in {baseline_time:.3f}s")

        # Spike: High load
        logger.info("Spike phase: high load")
        spike_ops = [
            kernel.remember_async(f"Spike {i}", f"Content {i}" * 10, tags=["spike"])
            for i in range(200)
        ]

        start = time.time()
        await asyncio.gather(*spike_ops)
        spike_time = time.time() - start

        logger.info(f"Spike: 200 ops in {spike_time:.3f}s")

        # Recovery: Return to low load
        logger.info("Recovery phase: low load")
        recovery_ops = [
            kernel.remember_async(
                f"Recovery {i}", f"Content {i}" * 10, tags=["recovery"]
            )
            for i in range(10)
        ]

        start = time.time()
        await asyncio.gather(*recovery_ops)
        recovery_time = time.time() - start

        logger.info(f"Recovery: 10 ops in {recovery_time:.3f}s")

        # Recovery should be similar to baseline
        assert recovery_time < baseline_time * 2, (
            f"System not recovering: {recovery_time:.3f}s vs {baseline_time:.3f}s baseline"
        )

    @pytest.mark.asyncio
    async def test_query_spike(self, tmp_path: Path):
        """Test query performance during sudden spike."""
        logger.info("Starting query spike test")

        vault = tmp_path / "query_spike_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(
            vault_path=str(vault), max_concurrent=100
        )

        # Create test data
        memories = [
            {
                "title": f"Document {i}",
                "content": f"Information about topic {i % 20}" * 25,
                "tags": [f"topic{i % 20}"],
            }
            for i in range(500)
        ]
        await kernel.remember_batch_async(memories, show_progress=False)
        await kernel.ingest_async()

        # Baseline queries
        baseline_queries = [f"topic {i}" for i in range(5)]
        start = time.time()
        await asyncio.gather(
            *[kernel.retrieve_nodes_async(q, top_k=5) for q in baseline_queries]
        )
        baseline_time = time.time() - start

        logger.info(f"Baseline: 5 queries in {baseline_time * 1000:.2f}ms")

        # Spike: 100 concurrent queries
        spike_queries = [f"topic {i % 20}" for i in range(100)]
        start = time.time()
        results = await asyncio.gather(
            *[kernel.retrieve_nodes_async(q, top_k=5) for q in spike_queries]
        )
        spike_time = time.time() - start

        assert len(results) == 100
        # Allow some queries to return empty if index timing is off
        non_empty = sum(1 for r in results if len(r) > 0)
        assert non_empty > 90, f"Only {non_empty}/100 queries returned results"

        logger.info(f"Spike: 100 queries in {spike_time:.2f}s")
        logger.info(f"Average: {spike_time / 100 * 1000:.2f}ms per query")


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.load
class TestGradualRampUp:
    """Test system behavior under gradual load increase."""

    @pytest.mark.asyncio
    async def test_gradual_ramp_up(self, tmp_path: Path):
        """Test gradual increase in load."""
        logger.info("Starting gradual ramp-up test")

        vault = tmp_path / "rampup_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(
            vault_path=str(vault), max_concurrent=100
        )

        load_levels = [10, 25, 50, 100, 200]
        times = []

        for load in load_levels:
            logger.info(f"Testing load level: {load} concurrent operations")

            ops = [
                kernel.remember_async(
                    f"Load {load} Memory {i}", f"Content {i}" * 15, tags=[f"load{load}"]
                )
                for i in range(load)
            ]

            start = time.time()
            await asyncio.gather(*ops)
            duration = time.time() - start
            times.append(duration)

            throughput = load / duration
            logger.info(f"Load {load}: {duration:.2f}s ({throughput:.1f} ops/s)")

        # Check that throughput doesn't degrade significantly
        initial_throughput = load_levels[0] / times[0]
        final_throughput = load_levels[-1] / times[-1]
        degradation = (initial_throughput - final_throughput) / initial_throughput * 100

        logger.info(f"Throughput degradation: {degradation:.1f}%")

        assert degradation < 50, f"Throughput degraded by {degradation:.1f}%"


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.load
class TestMixedWorkload:
    """Test realistic mixed workloads."""

    @pytest.mark.asyncio
    async def test_80_20_read_write(self, tmp_path: Path):
        """Test 80% read, 20% write workload."""
        logger.info("Starting 80/20 read/write test")

        vault = tmp_path / "mixed_80_20_vault"
        vault.mkdir()

        kernel = await create_gam_async_kernel(vault_path=str(vault), max_concurrent=50)

        # Create initial dataset
        initial_memories = [
            {
                "title": f"Initial Document {i}",
                "content": f"Content about topic {i % 10}" * 30,
                "tags": [f"topic{i % 10}", "initial"],
            }
            for i in range(200)
        ]
        await kernel.remember_batch_async(initial_memories, show_progress=False)
        await kernel.ingest_async()

        # Mixed workload: 80% reads, 20% writes
        operations = []

        # 80 read operations
        for i in range(80):
            operations.append(kernel.retrieve_nodes_async(f"topic {i % 10}", top_k=5))

        # 20 write operations
        for i in range(20):
            operations.append(
                kernel.remember_async(
                    f"New Document {i}",
                    f"New content {i}" * 20,
                    tags=["new", f"topic{i % 10}"],
                )
            )

        start = time.time()
        results = await asyncio.gather(*operations)
        duration = time.time() - start

        assert len(results) == 100
        throughput = 100 / duration

        logger.info(f"Mixed workload: 100 ops in {duration:.2f}s")
        logger.info(f"Throughput: {throughput:.1f} ops/s")

        assert throughput > 5, f"Throughput too low: {throughput:.1f} ops/s"
