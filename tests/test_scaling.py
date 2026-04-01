"""Scaling benchmarks for MemoGraph.

Tests ingest and query performance at different vault sizes:
- 100 notes (small personal vault)
- 1,000 notes (active user)
- 10,000 notes (power user / team vault)

These tests are marked as @pytest.mark.benchmark and @pytest.mark.slow.
Run with: pytest tests/test_scaling.py -v
"""

import time
from pathlib import Path

import pytest

from memograph.core.kernel import MemoryKernel


def create_vault(vault_path: Path, num_notes: int) -> None:
    """Create a vault with N synthetic notes containing cross-links."""
    tags_pool = [
        "python",
        "docker",
        "kubernetes",
        "ml",
        "ai",
        "testing",
        "devops",
        "architecture",
        "database",
        "api",
        "security",
        "frontend",
        "backend",
        "cloud",
        "performance",
    ]

    for i in range(num_notes):
        title = f"Note {i:05d}"
        slug = f"note-{i:05d}"

        # Create cross-links to nearby notes
        links = []
        if i > 0:
            links.append(f"note-{i - 1:05d}")
        if i > 10:
            links.append(f"note-{i - 10:05d}")

        link_text = " ".join(f"[[{link}]]" for link in links)

        # Assign 2-3 tags from the pool
        note_tags = [tags_pool[i % len(tags_pool)], tags_pool[(i * 3) % len(tags_pool)]]
        tags_line = " ".join(f"#{t}" for t in note_tags)

        content = (
            f"---\n"
            f"title: {title}\n"
            f"memory_type: semantic\n"
            f"salience: {0.3 + (i % 7) * 0.1:.1f}\n"
            f"---\n\n"
            f"This is note number {i} about {tags_pool[i % len(tags_pool)]}.\n"
            f"It contains information relevant to software engineering.\n"
            f"{link_text}\n\n"
            f"{tags_line}\n"
        )
        (vault_path / f"{slug}.md").write_text(content, encoding="utf-8")


@pytest.fixture
def vault_100(tmp_path):
    vault = tmp_path / "vault100"
    vault.mkdir()
    create_vault(vault, 100)
    return vault


@pytest.fixture
def vault_1k(tmp_path):
    vault = tmp_path / "vault1k"
    vault.mkdir()
    create_vault(vault, 1000)
    return vault


@pytest.fixture
def vault_10k(tmp_path):
    vault = tmp_path / "vault10k"
    vault.mkdir()
    create_vault(vault, 10000)
    return vault


class TestIngestPerformance:
    """Benchmark vault ingestion at different scales."""

    @pytest.mark.benchmark
    def test_ingest_100(self, vault_100):
        """Benchmark: ingest 100 notes."""
        kernel = MemoryKernel(vault_path=str(vault_100))
        start = time.time()
        stats = kernel.ingest()
        duration = time.time() - start

        assert stats["total"] == 100
        assert duration < 5.0, f"Ingest 100 notes took {duration:.2f}s (limit: 5s)"
        print(f"\n  Ingest 100 notes: {duration:.3f}s ({100 / duration:.0f} notes/sec)")

    @pytest.mark.benchmark
    def test_ingest_1k(self, vault_1k):
        """Benchmark: ingest 1,000 notes."""
        kernel = MemoryKernel(vault_path=str(vault_1k))
        start = time.time()
        stats = kernel.ingest()
        duration = time.time() - start

        assert stats["total"] == 1000
        assert duration < 30.0, f"Ingest 1K notes took {duration:.2f}s (limit: 30s)"
        print(f"\n  Ingest 1K notes: {duration:.3f}s ({1000 / duration:.0f} notes/sec)")

    @pytest.mark.benchmark
    @pytest.mark.slow
    def test_ingest_10k(self, vault_10k):
        """Benchmark: ingest 10,000 notes."""
        kernel = MemoryKernel(vault_path=str(vault_10k))
        start = time.time()
        stats = kernel.ingest()
        duration = time.time() - start

        assert stats["total"] == 10000
        assert duration < 180.0, f"Ingest 10K notes took {duration:.2f}s (limit: 180s)"
        print(
            f"\n  Ingest 10K notes: {duration:.3f}s ({10000 / duration:.0f} notes/sec)"
        )


class TestQueryPerformance:
    """Benchmark query performance at different scales."""

    @pytest.mark.benchmark
    def test_query_100(self, vault_100):
        """Benchmark: query 100-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_100))
        kernel.ingest()

        start = time.time()
        for query in ["python", "docker", "machine learning", "testing", "api"]:
            kernel.retrieve_nodes(query, top_k=10)
        duration = time.time() - start

        avg_ms = (duration / 5) * 1000
        assert avg_ms < 500, (
            f"Avg query on 100 notes took {avg_ms:.1f}ms (limit: 500ms)"
        )
        print(f"\n  Query 100 notes: avg {avg_ms:.1f}ms per query")

    @pytest.mark.benchmark
    def test_query_1k(self, vault_1k):
        """Benchmark: query 1,000-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_1k))
        kernel.ingest()

        start = time.time()
        for query in ["python", "docker", "machine learning", "testing", "api"]:
            kernel.retrieve_nodes(query, top_k=10)
        duration = time.time() - start

        avg_ms = (duration / 5) * 1000
        assert avg_ms < 2000, (
            f"Avg query on 1K notes took {avg_ms:.1f}ms (limit: 2000ms)"
        )
        print(f"\n  Query 1K notes: avg {avg_ms:.1f}ms per query")

    @pytest.mark.benchmark
    @pytest.mark.slow
    def test_query_10k(self, vault_10k):
        """Benchmark: query 10,000-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_10k))
        kernel.ingest()

        start = time.time()
        for query in ["python", "docker", "machine learning", "testing", "api"]:
            kernel.retrieve_nodes(query, top_k=10)
        duration = time.time() - start

        avg_ms = (duration / 5) * 1000
        assert avg_ms < 10000, (
            f"Avg query on 10K notes took {avg_ms:.1f}ms (limit: 10s)"
        )
        print(f"\n  Query 10K notes: avg {avg_ms:.1f}ms per query")


class TestGraphTraversalPerformance:
    """Benchmark graph traversal at different scales."""

    @pytest.mark.benchmark
    def test_graph_neighbors_1k(self, vault_1k):
        """Benchmark: graph traversal depth=2 on 1K-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_1k))
        kernel.ingest()

        start = time.time()
        for i in range(0, 100, 10):
            node_id = f"note-{i:05d}"
            kernel.graph.neighbors(node_id, depth=2)
        duration = time.time() - start

        avg_ms = (duration / 10) * 1000
        print(f"\n  Graph traversal (depth=2) on 1K: avg {avg_ms:.1f}ms")

    @pytest.mark.benchmark
    def test_graph_find_path_1k(self, vault_1k):
        """Benchmark: find_path on 1K-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_1k))
        kernel.ingest()

        start = time.time()
        kernel.graph.find_path("note-00000", "note-00050")
        kernel.graph.find_path("note-00000", "note-00500")
        kernel.graph.find_path("note-00100", "note-00900")
        duration = time.time() - start

        avg_ms = (duration / 3) * 1000
        print(f"\n  find_path on 1K: avg {avg_ms:.1f}ms")


class TestContextWindowPerformance:
    """Benchmark context window generation."""

    @pytest.mark.benchmark
    def test_context_window_1k(self, vault_1k):
        """Benchmark: context_window on 1K-note vault."""
        kernel = MemoryKernel(vault_path=str(vault_1k))
        kernel.ingest()

        start = time.time()
        for query in ["python tips", "docker setup", "testing guide"]:
            kernel.context_window(query, top_k=10, token_limit=4096)
        duration = time.time() - start

        avg_ms = (duration / 3) * 1000
        print(f"\n  context_window on 1K: avg {avg_ms:.1f}ms")


class TestMemoryUsage:
    """Test memory footprint at different scales."""

    @pytest.mark.benchmark
    def test_memory_footprint_1k(self, vault_1k):
        """Measure memory footprint with 1K notes."""
        import sys

        kernel = MemoryKernel(vault_path=str(vault_1k))
        kernel.ingest()

        # Approximate memory by counting nodes and their content
        nodes = kernel.graph.all_nodes()
        total_content_bytes = sum(
            sys.getsizeof(n.content) + sys.getsizeof(n.title) for n in nodes
        )
        total_content_mb = total_content_bytes / (1024 * 1024)

        print(f"\n  1K notes memory: ~{total_content_mb:.2f} MB content")
        print(f"  Nodes: {len(nodes)}")
        print(f"  Graph stats: {kernel.graph.get_stats().to_dict()}")

        # Should be well under 100MB for 1K notes
        assert total_content_mb < 100
