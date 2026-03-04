"""Tests for embedding adapters and functionality."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from memograph import MemoryKernel, MemoryType
from memograph.adapters.embeddings.base import EmbeddingAdapter
from memograph.core.graph import VaultGraph
from memograph.core.indexer import VaultIndexer
from memograph.core.node import MemoryNode
from memograph.core.retriever import HybridRetriever


class MockEmbeddingAdapter(EmbeddingAdapter):
    """Mock embedding adapter for testing."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.call_count = 0

    def embed(self, text: str) -> list[float]:
        """Return a simple mock embedding based on text length."""
        self.call_count += 1
        # Create deterministic embedding based on text
        base = len(text) / 100.0
        return [base + i * 0.01 for i in range(self.dimension)]


class EmbeddingAdapterTests(unittest.TestCase):
    def test_mock_adapter_generates_embeddings(self):
        adapter = MockEmbeddingAdapter(dimension=5)
        embedding = adapter.embed("test text")

        self.assertEqual(len(embedding), 5)
        self.assertIsInstance(embedding[0], float)

    def test_batch_embedding_calls_embed(self):
        adapter = MockEmbeddingAdapter()
        texts = ["first", "second", "third"]

        embeddings = adapter.embed_batch(texts)

        self.assertEqual(len(embeddings), 3)
        self.assertEqual(adapter.call_count, 3)


class IndexerEmbeddingTests(unittest.TestCase):
    def test_indexer_generates_embeddings_during_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("Test content", encoding="utf-8")

            adapter = MockEmbeddingAdapter(dimension=5)
            indexer = VaultIndexer(root, embedding_adapter=adapter)

            graph = VaultGraph()
            indexed, _ = indexer.index(graph)

            self.assertEqual(indexed, 1)
            self.assertEqual(adapter.call_count, 1)

            # Check node has embedding
            node = graph.get("note")
            self.assertIsNotNone(node.embedding)
            self.assertEqual(len(node.embedding), 5)

    def test_indexer_caches_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("Test content", encoding="utf-8")

            adapter = MockEmbeddingAdapter()
            indexer = VaultIndexer(root, embedding_adapter=adapter)

            # First index
            graph1 = VaultGraph()
            indexer.index(graph1)
            first_call_count = adapter.call_count

            # Second index (should load from cache)
            graph2 = VaultGraph()
            indexed, skipped = indexer.index(graph2)

            # Should have skipped the file and loaded embedding from cache
            self.assertEqual(skipped, 1)
            self.assertEqual(indexed, 0)
            # No new embed() calls
            self.assertEqual(adapter.call_count, first_call_count)

            # Verify embedding was restored
            node = graph2.get("note")
            self.assertIsNotNone(node.embedding)

    def test_indexer_works_without_embedding_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("Test content", encoding="utf-8")

            indexer = VaultIndexer(root, embedding_adapter=None)

            graph = VaultGraph()
            indexed, _ = indexer.index(graph)

            self.assertEqual(indexed, 1)
            node = graph.get("note")
            self.assertIsNone(node.embedding)


class RetrieverEmbeddingTests(unittest.TestCase):
    def test_retriever_uses_embeddings_for_reranking(self):
        adapter = MockEmbeddingAdapter(dimension=5)
        graph = VaultGraph()

        # Add test nodes
        for i in range(3):
            node = MemoryNode(
                id=f"node{i}",
                title=f"Node {i}",
                content=f"Content {i}" * 10,  # Different lengths
                memory_type=MemoryType.SEMANTIC,
                tags=["test"],
            )
            graph.add_node(node)

        retriever = HybridRetriever(graph, embedding_adapter=adapter)

        # Retrieve with embeddings
        results = retriever.retrieve(
            query="test query", seed_ids=["node0", "node1", "node2"], top_k=3
        )

        # Should have called embed for query + any nodes without embeddings
        self.assertGreater(adapter.call_count, 0)
        self.assertEqual(len(results), 3)

    def test_retriever_calculates_cosine_similarity(self):
        retriever = HybridRetriever(VaultGraph())

        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]  # Same direction
        vec3 = [0.0, 1.0, 0.0]  # Orthogonal

        sim_same = retriever._cosine_similarity(vec1, vec2)
        sim_orthogonal = retriever._cosine_similarity(vec1, vec3)

        self.assertAlmostEqual(sim_same, 1.0, places=5)
        self.assertAlmostEqual(sim_orthogonal, 0.0, places=5)

    def test_retriever_handles_zero_vectors(self):
        retriever = HybridRetriever(VaultGraph())

        zero = [0.0, 0.0, 0.0]
        vec = [1.0, 2.0, 3.0]

        sim = retriever._cosine_similarity(zero, vec)
        self.assertEqual(sim, 0.0)

    def test_retriever_works_without_embeddings(self):
        graph = VaultGraph()
        node = MemoryNode(
            id="test",
            title="Test",
            content="Test content",
            memory_type=MemoryType.SEMANTIC,
            salience=0.8,
        )
        graph.add_node(node)

        retriever = HybridRetriever(graph, embedding_adapter=None)

        # Should still work, just without embedding re-ranking
        results = retriever.retrieve(query="test", seed_ids=["test"], top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "test")


class KernelEmbeddingIntegrationTests(unittest.TestCase):
    def test_kernel_end_to_end_with_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MockEmbeddingAdapter()
            kernel = MemoryKernel(tmp, embedding_adapter=adapter)

            # Add memories
            kernel.remember(
                title="Python Guide",
                content="Python is a high-level programming language.",
                memory_type=MemoryType.SEMANTIC,
                tags=["python"],
            )

            kernel.remember(
                title="JavaScript Guide",
                content="JavaScript runs in web browsers.",
                memory_type=MemoryType.SEMANTIC,
                tags=["javascript"],
            )

            # Ingest (should generate embeddings)
            stats = kernel.ingest()
            self.assertEqual(stats["total"], 2)

            # Embeddings should have been generated
            self.assertGreater(adapter.call_count, 0)

            # Retrieve with semantic search
            nodes = kernel.retrieve_nodes(query="programming language", top_k=2)

            self.assertEqual(len(nodes), 2)
            # All nodes should have embeddings
            for node in nodes:
                self.assertIsNotNone(node.embedding)


if __name__ == "__main__":
    unittest.main()