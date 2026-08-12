"""Tests for the deterministic retrieval evaluation harness (R7).

See docs/RETRIEVAL_QUALITY_PLAN.md and memograph/eval/retrieval.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from memograph.core.kernel import MemoryKernel
from memograph.eval.retrieval import (
    GoldCase,
    evaluate_retrieval,
    f1_at_k,
    hit_at_k,
    load_gold_set,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    recall_at_k,
)


class TestMetrics:
    def test_precision_at_k(self):
        ranked = ["a", "b", "c", "d"]
        rel = {"a", "c"}
        assert precision_at_k(ranked, rel, 4) == pytest.approx(0.5)
        assert precision_at_k(ranked, rel, 2) == pytest.approx(0.5)
        assert precision_at_k(ranked, rel, 1) == pytest.approx(1.0)

    def test_precision_zero_k(self):
        assert precision_at_k(["a"], {"a"}, 0) == 0.0

    def test_recall_at_k(self):
        ranked = ["a", "b", "c"]
        rel = {"a", "z"}  # z never retrieved
        assert recall_at_k(ranked, rel, 3) == pytest.approx(0.5)

    def test_recall_no_relevant(self):
        assert recall_at_k(["a"], set(), 3) == 0.0

    def test_f1_combines(self):
        ranked = ["a", "b"]
        rel = {"a"}
        # p=0.5, r=1.0 -> f1 = 2*0.5*1/(1.5)
        assert f1_at_k(ranked, rel, 2) == pytest.approx(2 * 0.5 * 1.0 / 1.5)

    def test_f1_zero_when_no_overlap(self):
        assert f1_at_k(["x"], {"a"}, 1) == 0.0

    def test_hit_at_k(self):
        assert hit_at_k(["a", "b"], {"b"}, 2) == 1.0
        assert hit_at_k(["a", "b"], {"z"}, 2) == 0.0
        assert hit_at_k(["a", "b", "c"], {"c"}, 2) == 0.0  # c is at rank 3

    def test_reciprocal_rank(self):
        assert reciprocal_rank(["a", "b", "c"], {"b"}) == pytest.approx(0.5)
        assert reciprocal_rank(["a", "b"], {"a"}) == pytest.approx(1.0)
        assert reciprocal_rank(["a", "b"], {"z"}) == 0.0

    def test_ndcg_perfect_vs_worse(self):
        rel = {"a", "b"}
        perfect = ndcg_at_k(["a", "b", "c"], rel, 3)
        worse = ndcg_at_k(["c", "a", "b"], rel, 3)
        assert perfect == pytest.approx(1.0)
        assert worse < perfect

    def test_ndcg_no_relevant(self):
        assert ndcg_at_k(["a"], set(), 3) == 0.0


class TestGoldSet:
    def test_from_dict_normalizes_ids(self):
        case = GoldCase.from_dict({"query": "Q", "relevant_ids": ["Foo Bar", "BAZ"]})
        assert case.relevant_ids == {"foo-bar", "baz"}

    def test_from_dict_requires_query(self):
        with pytest.raises(ValueError):
            GoldCase.from_dict({"relevant_ids": ["a"]})

    def test_load_gold_set_list_and_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "list.json"
            p1.write_text(
                json.dumps([{"query": "q1", "relevant_ids": ["a"]}]),
                encoding="utf-8",
            )
            p2 = Path(tmp) / "wrapped.json"
            p2.write_text(
                json.dumps({"cases": [{"query": "q2", "relevant_ids": ["b"]}]}),
                encoding="utf-8",
            )
            assert len(load_gold_set(p1)) == 1
            assert len(load_gold_set(p2)) == 1


class TestEvaluateRetrieval:
    def _make_vault(self, tmp: str) -> MemoryKernel:
        root = Path(tmp)
        notes = {
            "python-async": ("Python async", "async await coroutines event loop"),
            "fastapi-deps": ("FastAPI dependencies", "Depends dependency injection"),
            "cooking": ("Cooking", "sourdough bread baking recipe"),
        }
        for nid, (title, body) in notes.items():
            (root / f"{nid}.md").write_text(
                f"---\nid: {nid}\ntitle: {title}\n---\n\n{body}\n",
                encoding="utf-8",
            )
        kernel = MemoryKernel(vault_path=str(root))
        kernel.ingest(force=True)
        return kernel

    def test_report_structure_and_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = self._make_vault(tmp)
            gold = [
                GoldCase(query="async coroutines", relevant_ids={"python-async"}),
                GoldCase(query="dependency injection", relevant_ids={"fastapi-deps"}),
            ]
            report = evaluate_retrieval(kernel, gold, top_k=3)
            assert len(report.cases) == 2
            assert "mrr" in report.aggregate
            assert "f1@3" in report.aggregate
            # Relevant notes should be found (hit@3 == 1 for both).
            assert report.aggregate["hit@3"] == pytest.approx(1.0)

    def test_relevant_note_ranks_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = self._make_vault(tmp)
            gold = [GoldCase(query="async coroutines", relevant_ids={"python-async"})]
            report = evaluate_retrieval(kernel, gold, top_k=3)
            assert report.cases[0].retrieved_ids[0] == "python-async"
            assert report.cases[0].metrics["mrr"] == pytest.approx(1.0)

    def test_to_dict_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = self._make_vault(tmp)
            gold = [GoldCase(query="bread", relevant_ids={"cooking"})]
            report = evaluate_retrieval(kernel, gold, top_k=2)
            # Round-trips through JSON without error.
            json.dumps(report.to_dict())
