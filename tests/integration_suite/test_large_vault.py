"""Performance integration tests for large Obsidian vaults.

This test suite focuses on performance testing with large datasets,
measuring sync speed, memory usage, and throughput for various vault sizes.

Test Coverage:
- Performance benchmarks for 10, 100, 1000 note vaults
- Memory usage patterns
- Sync speed measurements
- Throughput testing
- Batch processing performance
- Graph operations with large datasets
- Resource utilization
"""

import os
import time
from pathlib import Path

import psutil
import pytest

from memograph.integrations.obsidian.conflict_resolver import ConflictStrategy
from memograph.integrations.obsidian.sync import ObsidianSync

# These are performance/throughput BENCHMARKS with wall-clock and memory
# assertions that are inherently unreliable on shared CI runners (load,
# virtualization, and slow macOS/Windows agents make timings vary wildly).
# They are valuable locally and in a dedicated perf environment, but must not
# gate the correctness test matrix. Skip the whole module under CI
# (GitHub Actions sets CI=true); run locally with CI unset to exercise them.
pytestmark = pytest.mark.skipif(
    os.environ.get("CI", "").lower() in {"1", "true", "yes"},
    reason="performance benchmark suite: timing/memory assertions are unstable "
    "on shared CI runners; run locally or in the dedicated perf job.",
)


@pytest.fixture
def performance_vault(tmp_path):
    """Create a temporary vault for performance testing."""
    vault = tmp_path / "perf_vault"
    vault.mkdir()
    return vault


@pytest.fixture
def memograph_vault(tmp_path):
    """Create a temporary MemoGraph vault."""
    vault = tmp_path / "memograph_vault"
    vault.mkdir()
    return vault


@pytest.fixture
def sync_engine(performance_vault, memograph_vault):
    """Create a sync engine for performance tests."""
    return ObsidianSync(
        vault_path=performance_vault,
        memograph_vault=memograph_vault,
        conflict_strategy=ConflictStrategy.NEWEST_WINS,
    )


def create_test_vault(vault_path: Path, num_files: int) -> list[Path]:
    """Create a test vault with specified number of files."""
    # Ensure vault directory exists
    vault_path.mkdir(parents=True, exist_ok=True)
    files = []

    for i in range(num_files):
        # Create some variety in file sizes and complexity
        if i % 10 == 0:
            # Every 10th file is more complex
            content = f"""---
title: Complex Note {i}
tags: [test, performance, complex, tag{i}]
created: 2026-01-01T{i % 24:02d}:00:00Z
memory_type: semantic
salience: {0.5 + (i % 50) / 100}
---

# Complex Note {i}

This is a more complex note with multiple sections.

## Section 1: Introduction

This note contains [[note_{i - 1}]] and [[note_{i + 1}]] references.

## Section 2: Content

Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

### Subsection 2.1

More content with #tag{i} and #hashtag references.

## Section 3: Code

```python
def example_{i}():
    return "result {i}"
```

## Section 4: Lists

- Item 1 with [[another_link]]
- Item 2 with #tag
- Item 3 with text
"""
        else:
            # Regular simple notes
            content = f"""---
title: Note {i}
tags: [test, perf]
---

# Note {i}

This is test note number {i} for performance testing.

It contains some content and a [[link_{i}]].
"""

        file_path = vault_path / f"note_{i:04d}.md"
        file_path.write_text(content, encoding="utf-8")
        files.append(file_path)

    return files


def measure_memory():
    """Measure current process memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


class TestSmallVaultPerformance:
    """Test performance with small vaults (10-50 files)."""

    @pytest.mark.asyncio
    async def test_sync_10_files_performance(self, sync_engine, performance_vault):
        """Test sync performance with 10 files."""
        # Create vault
        _files = create_test_vault(performance_vault, 10)

        # Measure sync time
        start_time = time.time()
        stats = await sync_engine.pull_from_obsidian()
        sync_time = time.time() - start_time

        # Assertions
        assert stats["count"] == 10
        assert sync_time < 5.0  # Should complete in under 5 seconds

        print(
            f"\n10 files sync time: {sync_time:.2f}s ({10 / sync_time:.1f} files/sec)"
        )

    @pytest.mark.asyncio
    async def test_sync_50_files_performance(self, sync_engine, performance_vault):
        """Test sync performance with 50 files."""
        _files = create_test_vault(performance_vault, 50)

        start_time = time.time()
        stats = await sync_engine.pull_from_obsidian()
        sync_time = time.time() - start_time

        assert stats["count"] == 50
        assert (
            sync_time < 30.0
        )  # Should complete in under 30 seconds (generous for slow CI)

        print(
            f"\n50 files sync time: {sync_time:.2f}s ({50 / sync_time:.1f} files/sec)"
        )


class TestMediumVaultPerformance:
    """Test performance with medium vaults (100-500 files)."""

    @pytest.mark.asyncio
    async def test_sync_100_files_performance(self, sync_engine, performance_vault):
        """Test sync performance with 100 files."""
        _files = create_test_vault(performance_vault, 100)

        # Measure memory before
        mem_before = measure_memory()

        # Measure sync time
        start_time = time.time()
        stats = await sync_engine.batch_sync(direction="pull", batch_size=25)
        sync_time = time.time() - start_time

        # Measure memory after
        mem_after = measure_memory()
        mem_used = mem_after - mem_before

        # Assertions
        assert stats["pulled"] == 100
        assert sync_time < 30.0  # Should complete in under 30 seconds
        assert mem_used < 500  # Should use less than 500MB additional memory

        print(
            f"\n100 files sync time: {sync_time:.2f}s ({100 / sync_time:.1f} files/sec)"
        )
        print(f"Memory used: {mem_used:.1f} MB")

    @pytest.mark.asyncio
    async def test_batch_sync_optimization(self, sync_engine, performance_vault):
        """Test that batch syncing is faster than individual syncs."""
        _files = create_test_vault(performance_vault, 100)

        # Test batch sync
        start_batch = time.time()
        batch_stats = await sync_engine.batch_sync(direction="pull", batch_size=20)
        batch_time = time.time() - start_batch

        assert batch_stats["pulled"] == 100
        assert batch_time < 40.0

        print(f"\nBatch sync (100 files): {batch_time:.2f}s")
        print(f"Throughput: {100 / batch_time:.1f} files/sec")


class TestLargeVaultPerformance:
    """Test performance with large vaults (1000+ files)."""

    @pytest.mark.asyncio
    @pytest.mark.slow  # Mark as slow test
    async def test_sync_1000_files_performance(self, sync_engine, performance_vault):
        """Test sync performance with 1000 files."""
        _files = create_test_vault(performance_vault, 1000)

        mem_before = measure_memory()
        start_time = time.time()

        stats = await sync_engine.batch_sync(direction="pull", batch_size=50)

        sync_time = time.time() - start_time
        mem_after = measure_memory()
        mem_used = mem_after - mem_before

        assert stats["pulled"] == 1000
        assert sync_time < 300.0  # Should complete in under 5 minutes
        assert mem_used < 1000  # Should use less than 1GB

        throughput = 1000 / sync_time
        print(f"\n1000 files sync time: {sync_time:.2f}s")
        print(f"Throughput: {throughput:.1f} files/sec")
        print(f"Memory used: {mem_used:.1f} MB")
        print(f"Memory per file: {mem_used / 1000:.2f} MB")

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_incremental_sync_performance(self, sync_engine, performance_vault):
        """Test that incremental syncs are fast (only changed files)."""
        # Initial sync of 500 files
        files = create_test_vault(performance_vault, 500)

        initial_stats = await sync_engine.batch_sync(direction="pull")
        assert initial_stats["pulled"] == 500

        # Modify only 10 files
        for i in range(10):
            files[i].write_text(
                f"---\ntitle: Modified {i}\n---\n\n# Modified {i}", encoding="utf-8"
            )

        # Incremental sync should be much faster
        start_time = time.time()
        incremental_stats = await sync_engine.batch_sync(direction="pull")
        incremental_time = time.time() - start_time

        assert incremental_stats["pulled"] == 10  # Only modified files
        assert incremental_time < 5.0  # Should be very fast

        print(f"\nIncremental sync (10/500 files): {incremental_time:.2f}s")


class TestMemoryEfficiency:
    """Test memory efficiency and resource utilization."""

    @pytest.mark.asyncio
    async def test_memory_scaling(self, sync_engine, performance_vault):
        """Test that memory usage scales linearly with vault size."""
        sizes = [10, 50, 100]
        memory_per_size = {}

        for size in sizes:
            # Clear vault
            for f in performance_vault.glob("*.md"):
                f.unlink()

            # Create vault
            create_test_vault(performance_vault, size)

            # Measure memory
            mem_before = measure_memory()
            await sync_engine.batch_sync(direction="pull")
            mem_after = measure_memory()

            memory_per_size[size] = mem_after - mem_before

        # Check that memory scales reasonably
        # Memory per file should be relatively constant
        mem_per_file_10 = memory_per_size[10] / 10
        mem_per_file_100 = memory_per_size[100] / 100

        # Memory per file shouldn't increase significantly.
        # Use a floor of 0.1 MB/file to handle near-zero measurements
        # (OS memory management may not show measurable increase for small vaults)
        baseline = max(mem_per_file_10, 0.1)
        assert mem_per_file_100 < baseline * 2

        print("\nMemory scaling:")
        for size, mem in memory_per_size.items():
            print(f"  {size} files: {mem:.1f} MB ({mem / size:.2f} MB/file)")

    @pytest.mark.asyncio
    async def test_graph_memory_efficiency(self, sync_engine, performance_vault):
        """Test memory efficiency of graph operations."""
        # Create vault
        _files = create_test_vault(performance_vault, 200)

        await sync_engine.batch_sync(direction="pull")

        # Measure memory for graph operations
        mem_before = measure_memory()

        sync_engine.kernel.ingest()
        nodes = list(sync_engine.kernel.graph.all_nodes())

        mem_after = measure_memory()
        mem_used = mem_after - mem_before

        assert len(nodes) == 200
        assert mem_used < 300  # Graph should be memory efficient

        print(f"\nGraph memory for 200 nodes: {mem_used:.1f} MB")
        print(f"Memory per node: {mem_used / 200:.2f} MB")


class TestThroughputBenchmarks:
    """Test throughput and processing speed benchmarks."""

    @pytest.mark.asyncio
    async def test_parse_throughput(self, sync_engine, performance_vault):
        """Test file parsing throughput."""
        files = create_test_vault(performance_vault, 100)

        start_time = time.time()

        # Parse all files
        parsed_count = 0
        for file_path in files:
            try:
                parsed = sync_engine.parser.parse_file(file_path)
                if parsed:
                    parsed_count += 1
            except Exception:
                pass

        parse_time = time.time() - start_time
        throughput = parsed_count / parse_time

        assert parsed_count == 100
        assert throughput > 10  # Should parse at least 10 files/sec

        print(f"\nParsing throughput: {throughput:.1f} files/sec")

    @pytest.mark.asyncio
    async def test_write_throughput(self, sync_engine, performance_vault):
        """Test file writing throughput during push operations."""
        # Create memories in MemoGraph
        for i in range(100):
            file_path = performance_vault / f"write_test_{i}.md"
            await sync_engine.kernel.remember_async(
                title=f"Write Test {i}",
                content=f"Content {i}",
                meta={"source": "obsidian", "obsidian_path": str(file_path)},
            )

        sync_engine.kernel.ingest()

        # Measure write throughput
        start_time = time.time()
        stats = await sync_engine.push_to_obsidian()
        write_time = time.time() - start_time

        throughput = stats["count"] / write_time if write_time > 0 else 0

        assert stats["count"] == 100
        assert throughput > 5  # Should write at least 5 files/sec

        print(f"\nWriting throughput: {throughput:.1f} files/sec")


class TestConcurrentPerformance:
    """Test performance under concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_batch_operations(self, sync_engine, performance_vault):
        """Test performance of concurrent batch operations."""

        # Create two sets of files with unique names
        # Set 1: note_0000 to note_0049
        set1_dir = performance_vault / "set1"
        set1_dir.mkdir(exist_ok=True)
        set1 = create_test_vault(set1_dir, 50)

        # Set 2: note_0050 to note_0099 (offset by 50 to avoid name collisions)
        set2_dir = performance_vault / "set2"
        set2_dir.mkdir(exist_ok=True)
        set2 = []
        for i in range(50, 100):
            # Create files with offset numbering to avoid collisions
            file_path = set2_dir / f"note_{i:04d}.md"
            content = f"""---
title: Note {i}
tags: [test, perf]
---

# Note {i}

This is test note number {i} for performance testing.

It contains some content and a [[link_{i}]].
"""
            file_path.write_text(content, encoding="utf-8")
            set2.append(file_path)

        # Move files to main vault
        for f in set1 + set2:
            target = performance_vault / f.name
            f.rename(target)

        # Process concurrently
        start_time = time.time()
        stats = await sync_engine.batch_sync(direction="pull", batch_size=25)
        total_time = time.time() - start_time

        assert stats["pulled"] == 100, f"Expected 100 pulled, got {stats['pulled']}"
        assert total_time < 60.0  # Should handle concurrently

        print(f"\nConcurrent batch (100 files): {total_time:.2f}s")


class TestRealWorldScenarios:
    """Test performance in real-world usage scenarios."""

    @pytest.mark.asyncio
    async def test_daily_sync_pattern(self, sync_engine, performance_vault):
        """Test performance of daily sync pattern (small incremental updates)."""
        # Create initial vault (simulating existing vault)
        files = create_test_vault(performance_vault, 200)

        # Initial sync
        initial_stats = await sync_engine.batch_sync(direction="pull")
        assert initial_stats["pulled"] == 200

        # Simulate daily updates (modify ~5% of files)
        daily_updates = 10
        for i in range(daily_updates):
            files[i].write_text(
                f"---\ntitle: Daily Update {i}\n---\n\n# Updated", encoding="utf-8"
            )

        # Daily sync should be fast
        start_time = time.time()
        daily_stats = await sync_engine.batch_sync(direction="pull")
        daily_time = time.time() - start_time

        assert daily_stats["pulled"] == daily_updates
        assert (
            daily_time < 15.0
        )  # Daily syncs should be fast (generous limit for slow CI)

        print(f"\nDaily sync ({daily_updates}/200 files): {daily_time:.2f}s")

    @pytest.mark.asyncio
    async def test_weekly_large_sync(self, sync_engine, performance_vault):
        """Test performance of weekly sync with many changes."""
        # Create vault
        files = create_test_vault(performance_vault, 300)

        # Initial sync
        await sync_engine.batch_sync(direction="pull")

        # Simulate week's worth of changes (30% of files)
        weekly_updates = 90
        for i in range(weekly_updates):
            files[i].write_text(
                f"---\ntitle: Weekly Update {i}\n---\n\n# Updated this week",
                encoding="utf-8",
            )

        # Weekly sync
        start_time = time.time()
        weekly_stats = await sync_engine.batch_sync(direction="pull")
        weekly_time = time.time() - start_time

        assert weekly_stats["pulled"] == weekly_updates
        assert weekly_time < 30.0  # Should complete within 30 seconds

        print(f"\nWeekly sync ({weekly_updates}/300 files): {weekly_time:.2f}s")


class TestScalingLimits:
    """Test scaling limits and edge cases."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_max_practical_vault_size(self, sync_engine, performance_vault):
        """Test with maximum practical vault size."""
        # Using 500 files for practicality in testing
        _files = create_test_vault(performance_vault, 500)

        mem_before = measure_memory()
        start_time = time.time()

        stats = await sync_engine.batch_sync(direction="pull", batch_size=100)

        total_time = time.time() - start_time
        mem_after = measure_memory()
        mem_used = mem_after - mem_before

        assert stats["pulled"] == 500

        # Performance targets for 500 files
        throughput = 500 / total_time
        assert throughput > 3  # At least 3 files/sec
        assert mem_used < 1500  # Less than 1.5GB

        print("\n500 files sync:")
        print(f"  Time: {total_time:.2f}s")
        print(f"  Throughput: {throughput:.1f} files/sec")
        print(f"  Memory: {mem_used:.1f} MB")

    @pytest.mark.asyncio
    async def test_deeply_nested_structure_performance(
        self, sync_engine, performance_vault
    ):
        """Test performance with deeply nested directory structure."""
        # Create deep nesting
        files = []
        for i in range(100):
            # Create path with 5 levels of nesting
            nested_path = performance_vault / "l1" / "l2" / "l3" / "l4" / "l5"
            nested_path.mkdir(parents=True, exist_ok=True)

            file_path = nested_path / f"deep_{i}.md"
            file_path.write_text(
                f"---\ntitle: Deep {i}\n---\n\n# Deep File {i}", encoding="utf-8"
            )
            files.append(file_path)

        # Sync and measure
        start_time = time.time()
        stats = await sync_engine.batch_sync(direction="pull")
        sync_time = time.time() - start_time

        assert stats["pulled"] == 100
        assert (
            sync_time < 30.0
        )  # Deep nesting shouldn't significantly impact performance

        print(f"\nDeep nesting (100 files, 5 levels): {sync_time:.2f}s")


class TestPerformanceRegression:
    """Test for performance regressions."""

    @pytest.mark.asyncio
    async def test_baseline_performance_100_files(self, sync_engine, performance_vault):
        """Establish baseline performance for 100 files."""
        _files = create_test_vault(performance_vault, 100)

        # Run multiple times to get average
        times = []
        for run in range(3):
            # Clear state between runs
            for f in performance_vault.glob("*.md"):
                f.unlink()
            _files = create_test_vault(performance_vault, 100)

            start = time.time()
            await sync_engine.batch_sync(direction="pull")
            times.append(time.time() - start)

        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)

        # Performance target: average < 25s, max < 35s
        assert avg_time < 25.0
        assert max_time < 35.0

        print("\n100 files baseline performance:")
        print(f"  Average: {avg_time:.2f}s")
        print(f"  Min: {min_time:.2f}s")
        print(f"  Max: {max_time:.2f}s")

    @pytest.mark.asyncio
    async def test_consistency_across_runs(self, sync_engine, performance_vault):
        """Test that performance is consistent across multiple runs."""
        _files = create_test_vault(performance_vault, 50)

        times = []
        for run in range(5):
            start = time.time()
            # Re-sync same files (should be fast due to caching)
            _stats = await sync_engine.batch_sync(direction="pull")
            times.append(time.time() - start)

        # After first sync, subsequent syncs should be consistently fast
        subsequent_times = times[1:]
        avg_subsequent = sum(subsequent_times) / len(subsequent_times)

        # Subsequent syncs should be very fast (< 2s) due to no changes
        assert avg_subsequent < 2.0

        print("\nConsistency test (50 files):")
        print(f"  First sync: {times[0]:.2f}s")
        print(f"  Avg subsequent: {avg_subsequent:.2f}s")


class TestResourceCleanup:
    """Test resource cleanup and memory management."""

    @pytest.mark.asyncio
    async def test_memory_cleanup_after_large_sync(
        self, sync_engine, performance_vault
    ):
        """Test that memory is properly cleaned up after large sync."""
        import gc

        # Create large vault
        _files = create_test_vault(performance_vault, 200)

        # Measure baseline memory
        gc.collect()
        mem_baseline = measure_memory()

        # Perform large sync
        await sync_engine.batch_sync(direction="pull")
        mem_after_sync = measure_memory()

        # Force cleanup
        sync_engine.kernel.ingest()
        gc.collect()
        mem_after_cleanup = measure_memory()

        # Memory after cleanup should be close to baseline
        memory_retained = mem_after_cleanup - mem_baseline

        # Should not retain more than 200MB after cleanup
        assert memory_retained < 200

        print("\nMemory cleanup (200 files):")
        print(f"  Baseline: {mem_baseline:.1f} MB")
        print(f"  After sync: {mem_after_sync:.1f} MB")
        print(f"  After cleanup: {mem_after_cleanup:.1f} MB")
        print(f"  Retained: {memory_retained:.1f} MB")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not slow"])
