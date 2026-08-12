"""Deterministic, offline evaluation harnesses for MemoGraph.

Complementary to the LLM-judged benchmark in ``benchmarks/`` / ``paper/`` —
this package measures retrieval RANKING quality (precision/recall/F1/MRR/nDCG)
with no model calls, suitable for CI regression gating.
"""

from memograph.eval.retrieval import (
    EvalReport,
    GoldCase,
    evaluate_retrieval,
    load_gold_set,
)

__all__ = ["EvalReport", "GoldCase", "evaluate_retrieval", "load_gold_set"]
