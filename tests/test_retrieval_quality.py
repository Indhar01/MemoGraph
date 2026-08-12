"""Tests for retrieval quality improvements R1 (scored seeds) + R2 (RRF fusion).

See docs/RETRIEVAL_QUALITY_PLAN.md.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from memograph.core.enums import MemoryType
from memograph.core.graph import VaultGraph
from memograph.core.kernel import MemoryKernel
from memograph.core.node import MemoryNode
from memograph.core.retriever import (
    HybridRetriever,
    bm25_scores,
    reciprocal_rank_fusion,
)


def _node(nid: str, title: str, content: str, salience: float = 0.5) -> MemoryNode:
    return MemoryNode(
        id=nid,
        title=title,
        content=content,
        memory_type=MemoryType.SEMANTIC,
        salience=salience,
    )


class _FakeEmbeddings:
    """Deterministic toy embedder: bag-of-2-dims keyed on presence of words."""

    def embed(self, text: str) -> list[float]:
        t = (text or "").lower()
        return [
            float(t.count("python")),
            float(t.count("graph")),
            float(len(t) % 7),
        ]


class TestBm25Scores:
    def test_relevant_node_scores_higher(self):
        nodes = [
            _node("a", "Python async", "async await coroutines in python"),
            _node("b", "Cooking", "how to bake sourdough bread"),
        ]
        scores = bm25_scores("python async", nodes)
        assert scores["a"] > scores["b"]

    def test_no_overlap_all_zero(self):
        nodes = [_node("a", "Cooking", "bread and butter")]
        scores = bm25_scores("quantum chromodynamics", nodes)
        assert scores["a"] == 0.0

    def test_empty_query_returns_zero_map(self):
        nodes = [_node("a", "T", "c")]
        assert bm25_scores("", nodes) == {"a": 0.0}

    def test_empty_nodes(self):
        assert bm25_scores("anything", []) == {}


class TestReciprocalRankFusion:
    def test_item_ranked_high_in_both_wins(self):
        lex = ["a", "b", "c"]
        sem = ["a", "c", "b"]
        fused = reciprocal_rank_fusion([lex, sem])
        # "a" is first in both -> highest fused score
        assert max(fused, key=fused.get) == "a"

    def test_fusion_combines_disjoint_rankings(self):
        fused = reciprocal_rank_fusion([["a"], ["b"]])
        # both appear; both at rank 0 -> equal score
        assert fused["a"] == fused["b"]

    def test_empty(self):
        assert reciprocal_rank_fusion([]) == {}


class TestHybridRank:
    def test_fuses_lexical_and_semantic(self):
        graph = VaultGraph()
        n_py = _node("py", "Python graphs", "python graph traversal networkx")
        n_graph = _node("gr", "Graph theory", "graph nodes edges vertices")
        n_other = _node("ot", "Gardening", "plants soil water sunlight")
        for n in (n_py, n_graph, n_other):
            graph.add_node(n)

        retriever = HybridRetriever(graph, embedding_adapter=_FakeEmbeddings())
        results = retriever.retrieve(query="python graph", top_k=3)
        ids = [n.id for n in results]
        # The two on-topic notes must outrank the gardening note.
        assert ids.index("py") < ids.index("ot")
        assert ids.index("gr") < ids.index("ot")

    def test_bm25_only_when_no_embeddings(self):
        graph = VaultGraph()
        graph.add_node(_node("a", "Python", "python code"))
        graph.add_node(_node("b", "Bread", "sourdough bread"))
        retriever = HybridRetriever(graph, embedding_adapter=None)
        results = retriever.retrieve(query="python", top_k=2)
        assert results[0].id == "a"


class TestScoredSeeds:
    def test_seeds_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 30 notes all containing the query word -> old code seeded all 30.
            for i in range(30):
                (root / f"note{i}.md").write_text(
                    f"---\nid: note{i}\ntitle: Note {i}\n---\n\npython topic {i}\n",
                    encoding="utf-8",
                )
            kernel = MemoryKernel(vault_path=str(root))
            kernel._max_seeds = 5
            kernel.ingest(force=True)
            # Should not error and should return a bounded, ranked set.
            results = kernel.retrieve_nodes(query="python", top_k=10, use_cache=False)
            assert len(results) > 0
            assert len(results) <= 10

    def test_env_override_max_seeds(self, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_MAX_SEEDS", "3")
        with tempfile.TemporaryDirectory() as tmp:
            kernel = MemoryKernel(vault_path=tmp)
            assert kernel._max_seeds == 3

    def test_bad_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("MEMOGRAPH_MAX_SEEDS", "not-a-number")
        with tempfile.TemporaryDirectory() as tmp:
            kernel = MemoryKernel(vault_path=tmp)
            assert kernel._max_seeds == 20
